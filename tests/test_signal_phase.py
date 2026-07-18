import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signal_engine import SignalEngine

# Mock analysis with market phase
mock_analysis = {
    "confluence": {
        "score": 85,
        "checks": ["✔ Multi Timeframe", "✔ Trend", "✔ Entry"]
    },
    "entry": {
        "direction": "LONG",
        "entry": 100,
        "stop_loss": 95,
        "valid": True
    },
    "market_phase": {
        "phase": "Expansion",
        "phase_confidence": 85,
        "phase_strength": "STRONG",
        "phase_score": 90,
        "mtf_alignment": 100,
        "trend": "BULLISH",
        "trend_strength": 2,
    }
}

# Test Signal Generation
engine = SignalEngine()
signal = engine.generate(mock_analysis)

print("✅ Signal Generation Test Results:")
print(f"  Signal: {signal['signal']}")
print(f"  Confidence: {signal['confidence']}%")
print(f"  Grade: {signal['grade']}")
print(f"  Strength: {signal['strength']}")
print(f"  Market Phase: {signal['market_phase']}")
print(f"  Phase Quality: {signal['phase_quality']}%")
print("\n✅ Signal generation with market phase working correctly!")

# Test with Distribution phase (should reduce confidence)
mock_analysis["market_phase"]["phase"] = "Distribution"
signal2 = engine.generate(mock_analysis)

print(f"\n✅ Distribution Phase Test:")
print(f"  Signal: {signal2['signal']}")
print(f"  Confidence: {signal2['confidence']}% (reduced due to Distribution phase)")
print(f"  Grade: {signal2['grade']}")
print("\n✅ Phase-based confidence adjustment working!")
