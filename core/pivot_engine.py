class PivotEngine:

    def __init__(self, left=3, right=3):
        self.left = left
        self.right = right

    def find_pivots(self, candles):

        highs = []
        lows = []

        for i in range(self.left, len(candles) - self.right):

            high = candles[i][2]
            low = candles[i][3]

            is_high = True
            is_low = True

            for j in range(i - self.left, i + self.right + 1):

                if j == i:
                    continue

                if candles[j][2] >= high:
                    is_high = False

                if candles[j][3] <= low:
                    is_low = False

            if is_high:
                highs.append({
                    "index": i,
                    "price": high
                })

            if is_low:
                lows.append({
                    "index": i,
                    "price": low
                })

        return {
            "highs": highs,
            "lows": lows
        }
