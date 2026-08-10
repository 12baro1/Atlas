"""Local llama.cpp server lifecycle manager for Atlas."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class LlamaServerStatus:
    online: bool
    owner: str  # atlas | external | none
    base_url: str
    detail: str = ""


class LocalLlamaServerManager:
    """Starts/stops local llama-server when needed.

    - If server is already running at configured URL, does not spawn another one.
    - If Atlas spawned it, Atlas can stop it on shutdown.
    - If user started it externally, Atlas will not kill it.
    """

    def __init__(self, *, repo_root: Path, config):
        self.repo_root = Path(repo_root)
        self.config = config
        self._proc: subprocess.Popen | None = None
        self._spawned_by_atlas = False

    @property
    def base_url(self):
        host = str(getattr(self.config, "AI_LOCAL_HOST", "127.0.0.1") or "127.0.0.1").strip()
        port = int(getattr(self.config, "AI_LOCAL_PORT", 8080) or 8080)
        return f"http://{host}:{port}/v1"

    def status(self):
        if self._is_online():
            if self._spawned_by_atlas and self._proc is not None and self._proc.poll() is None:
                return LlamaServerStatus(True, "atlas", self.base_url, "running")
            return LlamaServerStatus(True, "external", self.base_url, "already_running")
        if self._spawned_by_atlas and self._proc is not None and self._proc.poll() is not None:
            return LlamaServerStatus(False, "atlas", self.base_url, f"exited:{self._proc.returncode}")
        return LlamaServerStatus(False, "none", self.base_url, "offline")

    def ensure_running(self, timeout_seconds=60.0):
        current = self.status()
        if current.online:
            return current

        if not bool(getattr(self.config, "AI_LOCAL_AUTO_START", True)):
            return LlamaServerStatus(False, "none", self.base_url, "auto_start_disabled")

        server_bin = self._resolve_llama_server_bin()
        if server_bin is None:
            return LlamaServerStatus(False, "none", self.base_url, "llama_server_not_found")

        model_path = self._resolve_model_path()
        if model_path is None or not model_path.exists():
            return LlamaServerStatus(False, "none", self.base_url, "model_not_found")

        cmd = [
            str(server_bin),
            "--host",
            str(getattr(self.config, "AI_LOCAL_HOST", "127.0.0.1")),
            "--port",
            str(int(getattr(self.config, "AI_LOCAL_PORT", 8080))),
            "-m",
            str(model_path),
            "--ctx-size",
            str(int(getattr(self.config, "AI_LOCAL_CONTEXT", 4096))),
            "--threads",
            str(self._resolved_threads()),
            "--parallel",
            str(max(1, int(getattr(self.config, "AI_LOCAL_PARALLEL_SLOTS", 1) or 1))),
            "--cache-ram",
            str(max(0, int(getattr(self.config, "AI_LOCAL_CACHE_RAM_MIB", 0) or 0))),
        ]
        if not bool(getattr(self.config, "AI_LOCAL_REASONING", False)):
            cmd.extend(["--reasoning", "off"])
        if not bool(getattr(self.config, "AI_LOCAL_WARMUP", False)):
            cmd.append("--no-warmup")
        if not bool(getattr(self.config, "AI_LOCAL_REPACK", False)):
            cmd.append("--no-repack")

        gpu_layers = int(getattr(self.config, "AI_LOCAL_GPU_LAYERS", 0) or 0)
        if gpu_layers > 0:
            cmd.extend(["-ngl", str(gpu_layers)])

        env = os.environ.copy()
        ld = self._resolved_ld_library_path()
        if ld:
            prev = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = ld if not prev else f"{ld}:{prev}"

        backend = self._resolved_backend_path()
        if backend:
            env["GGML_BACKEND_PATH"] = backend

        run_dir = self.repo_root / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "llama_server.log"
        log_handle = log_path.open("a", encoding="utf-8")

        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self.repo_root),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._spawned_by_atlas = True

        started = time.time()
        while time.time() - started < float(timeout_seconds):
            if self._proc.poll() is not None:
                return LlamaServerStatus(False, "atlas", self.base_url, f"spawn_failed:{self._proc.returncode}")
            if self._is_online():
                return LlamaServerStatus(True, "atlas", self.base_url, "started")
            time.sleep(0.4)

        return LlamaServerStatus(False, "atlas", self.base_url, "startup_timeout")

    def stop_if_owned(self, timeout=8.0):
        if not self._spawned_by_atlas:
            return False
        if self._proc is None:
            return False
        if self._proc.poll() is not None:
            return True

        self._proc.terminate()
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=3)
        return True

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _is_online(self):
        try:
            response = requests.get(f"{self.base_url}/models", timeout=2.5)
            if response.status_code == 200:
                payload = response.json()
                return isinstance(payload, dict) and "data" in payload
            return False
        except Exception:
            return False

    def _resolve_llama_server_bin(self):
        explicit = str(getattr(self.config, "AI_LOCAL_LLAMA_SERVER", "") or "").strip()
        if explicit:
            path = Path(explicit)
            if path.exists() and os.access(path, os.X_OK):
                return path

        env_bin = shutil.which("llama-server")
        if env_bin:
            return Path(env_bin)

        local_bin = self.repo_root / ".local" / "llama" / "bin" / "llama-server"
        if local_bin.exists() and os.access(local_bin, os.X_OK):
            return local_bin
        return None

    def _resolve_model_path(self):
        model = str(getattr(self.config, "AI_LOCAL_MODEL_FILE", "") or "").strip()
        if not model:
            return None
        path = Path(model)
        if not path.is_absolute():
            path = self.repo_root / path
        return path

    def _resolved_threads(self):
        configured = int(getattr(self.config, "AI_LOCAL_THREADS", 0) or 0)
        if configured > 0:
            return configured
        cpu_count = os.cpu_count() or 4
        return max(1, min(cpu_count, 8))

    def _resolved_ld_library_path(self):
        candidate = self.repo_root / ".local" / "llama" / "debs" / "usr" / "lib" / "aarch64-linux-gnu"
        candidate_llama = candidate / "llama"
        if candidate.exists() and candidate_llama.exists():
            return f"{candidate}:{candidate_llama}"
        return ""

    def _resolved_backend_path(self):
        explicit = str(getattr(self.config, "AI_LOCAL_GGML_BACKEND", "") or "").strip()
        if explicit:
            path = Path(explicit)
            if not path.is_absolute():
                path = self.repo_root / path
            if path.exists():
                return str(path)

        candidates = [
            self.repo_root / ".local" / "llama" / "debs" / "usr" / "lib" / "aarch64-linux-gnu" / "ggml" / "backends0" / "libggml-cpu-armv8.2_2.so",
            self.repo_root / ".local" / "llama" / "debs" / "usr" / "lib" / "aarch64-linux-gnu" / "ggml" / "backends0" / "libggml-cpu-armv8.2_1.so",
            self.repo_root / ".local" / "llama" / "debs" / "usr" / "lib" / "aarch64-linux-gnu" / "ggml" / "backends0" / "libggml-cpu-armv8.0_1.so",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return ""
