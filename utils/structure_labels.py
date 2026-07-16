

def label_swings(swings):

    if len(swings) < 2:
        return []

    labels = []

    last_high = None
    last_low = None

    for swing in swings:

        if swing.kind == "HIGH":

            if last_high is None:
                tag = "H?"

            elif swing.price > last_high:
                tag = "HH"

            else:
                tag = "LH"

            last_high = swing.price

        else:

            if last_low is None:
                tag = "L?"

            elif swing.price > last_low:
                tag = "HL"

            else:
                tag = "LL"

            last_low = swing.price

        labels.append({
            "index": swing.index,
            "price": swing.price,
            "type": swing.kind,
            "label": tag
        })

    return labels
