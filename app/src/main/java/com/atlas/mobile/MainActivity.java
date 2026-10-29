package com.atlas.mobile;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.graphics.Color;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import com.chaquo.python.Python;
import com.chaquo.python.PyException;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends Activity {
    private WebView webView;
    private TextView status;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean pageLoaded = false;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(9,11,16));
        getWindow().setNavigationBarColor(Color.rgb(9,11,16));
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(9,11,16));
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        webView.setWebViewClient(new WebViewClient());
        root.addView(webView, new FrameLayout.LayoutParams(-1,-1));
        status = new TextView(this);
        status.setText("Atlas başlatılıyor…");
        status.setTextColor(Color.WHITE);
        status.setTextSize(16);
        status.setGravity(android.view.Gravity.CENTER);
        status.setBackgroundColor(Color.rgb(9,11,16));
        root.addView(status, new FrameLayout.LayoutParams(-1,-1));
        setContentView(root);

        Thread pythonThread = new Thread(() -> {
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
                Python.getInstance().getModule("atlas_mobile").callAttr("main");
            } catch (PyException ex) {
                handler.post(() -> status.setText("Atlas başlatılamadı.\n" + ex.getMessage()));
            }
        }, "atlas-python-server");
        pythonThread.setDaemon(true);
        pythonThread.start();
        handler.postDelayed(this::loadWhenReady, 500);
    }

    private void loadWhenReady() {
        if (isFinishing() || pageLoaded) return;
        new Thread(() -> {
            boolean ready = false;
            for (int i=0; i<90 && !isFinishing(); i++) {
                try {
                    java.net.HttpURLConnection c = (java.net.HttpURLConnection)
                        new java.net.URL("http://127.0.0.1:8765/api/health").openConnection();
                    c.setConnectTimeout(500);
                    c.setReadTimeout(500);
                    ready = c.getResponseCode() == 200;
                    c.disconnect();
                    if (ready) break;
                } catch (Exception ignored) {}
                try { Thread.sleep(500); } catch (InterruptedException ignored) { return; }
            }
            final boolean serverReady = ready;
            handler.post(() -> {
                if (serverReady) {
                    pageLoaded = true;
                    webView.loadUrl("http://127.0.0.1:8765/");
                    status.setVisibility(View.GONE);
                } else {
                    status.setText("Atlas başlatılamadı. İnternet bağlantısını kontrol edip uygulamayı yeniden aç.");
                }
            });
        }, "atlas-server-check").start();
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
