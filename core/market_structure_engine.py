from core.pivot import Pivot

class MarketStructureEngine:

    def __init__(self):
        self.pivots=[]

    def find_pivots(self,candles,left=5,right=5):

        self.pivots=[]

        for i in range(left,len(candles)-right):

            high=candles[i].high
            low=candles[i].low

            is_high=True
            is_low=True

            for j in range(i-left,i+right+1):

                if j==i:
                    continue

                if candles[j].high>=high:
                    is_high=False

                if candles[j].low<=low:
                    is_low=False

            if is_high:

                self.pivots.append(
                    Pivot(
                        index=i,
                        price=high,
                        kind="HIGH"
                    )
                )

            if is_low:

                self.pivots.append(
                    Pivot(
                        index=i,
                        price=low,
                        kind="LOW"
                    )
                )

        self.pivots.sort(key=lambda x:x.index)

        return self.pivots


    def calculate_strength(self,candles):

        for pivot in self.pivots:

            left=max(0,pivot.index-10)
            right=min(len(candles),pivot.index+11)

            score=0

            if pivot.kind=="HIGH":

                for i in range(left,right):

                    if candles[i].high<pivot.price:
                        score+=1

            else:

                for i in range(left,right):

                    if candles[i].low>pivot.price:
                        score+=1

            pivot.strength=score

        return self.pivots


    def merge_pivots(self,max_distance=6):

        if len(self.pivots)<2:
            return self.pivots

        merged=[]

        current=self.pivots[0]

        for nxt in self.pivots[1:]:

            if (
                nxt.kind==current.kind
                and
                nxt.index-current.index<=max_distance
            ):

                if current.kind=="HIGH":

                    if nxt.price>current.price:
                        current=nxt

                else:

                    if nxt.price<current.price:
                        current=nxt

            else:

                merged.append(current)
                current=nxt

        merged.append(current)

        self.pivots=merged

        return self.pivots


    def filter_noise(self,min_strength=14):

        filtered=[]

        for pivot in self.pivots:

            if pivot.strength>=min_strength:

                pivot.confirmed=True

                filtered.append(pivot)

        self.pivots=filtered

        return self.pivots


    def validate_sequence(self):

        if len(self.pivots)<2:
            return self.pivots

        result=[self.pivots[0]]

        for pivot in self.pivots[1:]:

            last=result[-1]

            if pivot.kind!=last.kind:

                result.append(pivot)

                continue

            if pivot.kind=="HIGH":

                if pivot.price>last.price:
                    result[-1]=pivot

            else:

                if pivot.price<last.price:
                    result[-1]=pivot

        self.pivots=result

        return self.pivots
