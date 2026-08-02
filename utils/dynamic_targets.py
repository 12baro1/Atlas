"""
Dinamik TP/SL Hesaplama Motoru
Market Structure, FVG, Order Block ve ATR bazlı akıllı hedef belirleme.
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class DynamicTargetCalculator:
    """
    Profesyonel Seviye Dinamik TP/SL Hesaplayıcı
    Sabit RR yerine Market Structure, FVG ve Likidite bazlı hedefler belirler.
    """

    def __init__(self, atr_multiplier_sl: float = 1.5, atr_multiplier_tp: float = 2.0):
        self.atr_mult_sl = atr_multiplier_sl
        self.atr_mult_tp = atr_multiplier_tp

    def calculate_levels(self, signal_data: Dict, market_data: Dict) -> Dict:
        """
        Giriş fiyatına göre en uygun SL ve TP seviyelerini hesaplar.
        """
        try:
            entry_price = signal_data.get('entry_price', market_data.get('close', 0))
            if entry_price == 0:
                return self._fallback_rr(100, 'LONG')
                
            direction = signal_data.get('direction', 'LONG')
            atr = market_data.get('atr', 0.0)
            
            # 1. Structure Based Levels (Yapı Bazlı)
            structure_sl = self._get_structure_sl(signal_data, direction)
            structure_tp = self._get_structure_tp(signal_data, direction)

            # 2. ATR Based Levels (Volatilite Bazlı - Güvenlik Ağı)
            atr_sl = None
            atr_tp = None
            
            if atr > 0:
                if direction == 'LONG':
                    atr_sl = entry_price - (atr * self.atr_mult_sl)
                    atr_tp = entry_price + (atr * self.atr_mult_tp)
                else:
                    atr_sl = entry_price + (atr * self.atr_mult_sl)
                    atr_tp = entry_price - (atr * self.atr_mult_tp)

            # 3. En Mantıklı Seviyeyi Seç (Hybrid Approach)
            final_sl = self._select_safe_sl(structure_sl, atr_sl, direction, entry_price)
            final_tp = self._select_realistic_tp(structure_tp, atr_tp, direction, entry_price)

            if not final_sl or not final_tp:
                logger.warning("Hedef hesaplanamadı, varsayılan %2 RR kullanılıyor.")
                return self._fallback_rr(entry_price, direction)

            risk = abs(entry_price - final_sl)
            reward = abs(final_tp - entry_price)
            rr_ratio = reward / risk if risk > 0 else 0

            return {
                'entry': round(entry_price, 2),
                'sl': round(final_sl, 2),
                'tp': round(final_tp, 2),
                'rr': round(rr_ratio, 2),
                'reason': 'Structure + ATR Hybrid'
            }

        except Exception as e:
            logger.error(f"Dinamik hedef hesaplama hatası: {e}")
            return self._fallback_rr(signal_data.get('entry_price', 100), signal_data.get('direction', 'LONG'))

    def _get_structure_sl(self, data: Dict, direction: str) -> Optional[float]:
        """Order Block veya Swing Low/High tabanlı SL"""
        if direction == 'LONG':
            # Son swing low veya OB low'u
            return data.get('invalidation_point') or data.get('swing_low')
        else:
            # Son swing high veya OB high'u
            return data.get('invalidation_point') or data.get('swing_high')

    def _get_structure_tp(self, data: Dict, direction: str) -> Optional[float]:
        """Likidite havuzları veya ters OB tabanlı TP"""
        if direction == 'LONG':
            return data.get('liquidity_target') or data.get('swing_high')
        else:
            return data.get('liquidity_target') or data.get('swing_low')

    def _select_safe_sl(self, struct_sl: Optional[float], atr_sl: Optional[float], 
                        direction: str, entry: float) -> Optional[float]:
        """Güvenli SL seçimi"""
        if not struct_sl and not atr_sl:
            return None
        
        # İkisi de varsa, yapıyı koruyan (daha uzak) SL'i seç
        if struct_sl and atr_sl:
            if direction == 'LONG':
                return min(struct_sl, atr_sl) # Long'ta daha aşağısı güvenli
            else:
                return max(struct_sl, atr_sl) # Short'ta daha yukarısı güvenli
        return struct_sl if struct_sl else atr_sl

    def _select_realistic_tp(self, struct_tp: Optional[float], atr_tp: Optional[float], 
                             direction: str, entry: float) -> Optional[float]:
        """Gerçekçi TP seçimi (ilk direnç)"""
        if not struct_tp and not atr_tp:
            return None
        
        # İlk dirence ulaşmak daha olasıdır, o yüzden daha yakın olanı seç
        if struct_tp and atr_tp:
            if direction == 'LONG':
                return min(struct_tp, atr_tp)
            else:
                return max(struct_tp, atr_tp)
        return struct_tp if struct_tp else atr_tp

    def _fallback_rr(self, entry: float, direction: str) -> Dict:
        """Acil durum: Basit %2 RR"""
        risk_pct = 0.01
        if direction == 'LONG':
            sl = entry * (1 - risk_pct)
            tp = entry * (1 + (risk_pct * 2))
        else:
            sl = entry * (1 + risk_pct)
            tp = entry * (1 - (risk_pct * 2))
        
        return {
            'entry': round(entry, 2), 
            'sl': round(sl, 2), 
            'tp': round(tp, 2), 
            'rr': 2.0, 
            'reason': 'Fallback (Yetersiz Veri)'
        }
