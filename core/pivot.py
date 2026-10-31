from dataclasses import dataclass

@dataclass
class Pivot:

    index:int
    price:float
    kind:str

    strength:float=0.0

    confirmed:bool=False

    internal:bool=False

    external:bool=False

    label:str=""

    broken:bool=False

    swept:bool=False

    mitigated:bool=False

    # Candle index at which the right-side confirmation window has closed.
    confirmation_index:int=None
