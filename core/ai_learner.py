"""
AI Öğrenme Çekirdeği
Geçmiş işlemleri analiz ederek strateji optimizasyonu yapar.
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class AILearningCore:
    """
    Gerçek Zamanlı Öğrenme Motoru
    Kazanan işlemlerin özelliklerini (zaman, setup, parite) analiz eder
    ve sinyal skorlamasını dinamik olarak optimize eder.
    """

    def __init__(self, db_path: str = "trade_journal.json"):
        self.db_path = db_path
        self.memory_cache: List[Dict] = []
        self.load_memory()

    def load_memory(self):
        """Hafızayı diskten yükle"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Sadece son 100 işlemi hafızada tut (Performans için)
                    history = data.get('history', []) if isinstance(data, dict) else []
                    self.memory_cache = history[-100:] if history else []
                    logger.info(f"AI Hafıza yüklendi: {len(self.memory_cache)} işlem")
            except Exception as e:
                logger.error(f"AI Hafıza yükleme hatası: {e}")
                self.memory_cache = []
        else:
            logger.info("AI Hafıza dosyası bulunamadı, yeni oluşturulacak.")

    def record_trade_outcome(self, trade_data: Dict):
        """İşlem sonucunu kaydet ve hafızayı güncelle"""
        # Gerekli alanları ekle
        trade_record = {
            'symbol': trade_data.get('symbol', 'UNKNOWN'),
            'direction': trade_data.get('direction', 'LONG'),
            'outcome': trade_data.get('outcome', 'PENDING'), # WIN, LOSS, PENDING
            'rr': trade_data.get('rr', 0),
            'score': trade_data.get('score', 0),
            'setup_type': trade_data.get('setup_type', 'Unknown'),
            'hour': trade_data.get('hour', datetime.now().hour),
            'timestamp': datetime.now().isoformat()
        }
        
        self.memory_cache.append(trade_record)
        self._save_to_disk()
        logger.info(f"AI: İşlem kaydedildi -> {trade_record['symbol']} {trade_record['outcome']}")

    def analyze_and_adjust_score(self, base_score: float, context: Dict) -> float:
        """
        Mevcut bağlama (parite, saat, setup) göre geçmiş başarı oranını kontrol et
        ve skoru buna göre revize et.
        """
        if len(self.memory_cache) < 5:
            return base_score # Henüz yeterli veri yok

        relevant_trades = self._filter_relevant_trades(context)
        
        if not relevant_trades:
            return base_score

        wins = sum(1 for t in relevant_trades if t.get('outcome') == 'WIN')
        losses = sum(1 for t in relevant_trades if t.get('outcome') == 'LOSS')
        total = wins + losses
        
        if total == 0:
            return base_score
            
        win_rate = wins / total

        # Öğrenme Mantığı:
        # Eğer benzer durumlarda win_rate < %40 ise skoru düşür
        # Eğer win_rate > %70 ise skoru artır
        adjustment = 0
        if win_rate < 0.40:
            adjustment = -20 # Ciddi düşüş
            logger.warning(f"AI Uyarısı: {context.get('symbol')} için düşük başarı ({win_rate:.2f}). Skor düşürülüyor.")
        elif win_rate > 0.70:
            adjustment = 15 # Ödül
            logger.info(f"AI Onayı: {context.get('symbol')} için yüksek başarı ({win_rate:.2f}). Skor artırılıyor.")
        
        new_score = min(100, max(0, base_score + adjustment))
        return new_score

    def _filter_relevant_trades(self, context: Dict) -> List[Dict]:
        """Benzer koşulları bul"""
        symbol = context.get('symbol', '')
        hour = context.get('hour', datetime.now().hour)
        setup_type = context.get('setup_type', '') 

        filtered = []
        for trade in self.memory_cache:
            t_symbol = trade.get('symbol', '')
            t_hour = trade.get('hour', 0)
            t_setup = trade.get('setup_type', '')
            
            # Benzer koşulları yakala
            if t_symbol == symbol and t_setup == setup_type:
                filtered.append(trade)
            elif t_setup == setup_type and abs(t_hour - hour) <= 2: # Aynı setup, yakın saat
                filtered.append(trade)
        
        return filtered

    def _save_to_disk(self):
        """Atomik yazma işlemi (Veri bozulmasını önler)"""
        try:
            temp_path = self.db_path + ".tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump({'history': self.memory_cache}, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.db_path)
        except Exception as e:
            logger.error(f"AI Hafıza kaydetme hatası: {e}")

    def get_stats(self) -> Dict:
        """İstatistikleri döndür"""
        if not self.memory_cache:
            return {"message": "Henüz yeterli veri yok."}
        
        wins = sum(1 for t in self.memory_cache if t.get('outcome') == 'WIN')
        losses = sum(1 for t in self.memory_cache if t.get('outcome') == 'LOSS')
        total = wins + losses
        
        if total == 0:
            return {"message": "Henüz sonuçlanmış işlem yok."}
            
        win_rate = (wins / total) * 100
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": f"%{win_rate:.1f}",
            "last_10_performance": "Analiz ediliyor..."
        }
