"""Product names and which EQ curve each earbud expects.

Names and model ids come from the Nothing X device list. Feature commands
are queried from the earbuds themselves; this table is only used to recognise
a device and to pick the 3-band EQ frequencies the official app sends.
"""

from __future__ import annotations

from dataclasses import dataclass

MAC_PREFIXES = ("2C:BE:EB", "3C:B0:ED")


@dataclass(frozen=True)
class Model:
    model_id: str
    name: str
    aliases: tuple[str, ...]
    eq_profile: str = "3400"
    ear1_ring: bool = False


# Longer aliases must be matched before shorter ones ("Nothing Ear (2)"
# before "Nothing Ear"). The tuple is already in that order.
MODELS: tuple[Model, ...] = (
    Model("B157", "Nothing Ear (stick)", ("nothing ear (stick)", "nothing ear stick"), "stick"),
    Model("B174", "Nothing Ear (open)", ("nothing ear (open)", "nothing ear open")),
    Model("B190", "Nothing Ear (3a)", ("nothing ear (3a)",)),
    Model("B173", "Nothing Ear (3)", ("nothing ear (3)",), "3400"),
    Model("B201", "Nothing Ear (3)", ("nothing ear (3)",), "3400"),
    Model("B155", "Nothing Ear (2)", ("nothing ear (2)",)),
    Model("B181", "Nothing Ear (1)", ("nothing ear (1)",), ear1_ring=True),
    Model("B162", "Nothing Ear (a)", ("nothing ear (a)",)),
    Model("B183", "Nothing Ear (a)", ("nothing ear (a)",)),
    Model("B186", "Nothing Headphone (a)", ("nothing headphone (a)", "headphone (a)")),
    Model("B198", "Nothing Headphone (a)", ("nothing headphone (a)",)),
    Model("B170", "Nothing Headphone (1)", ("nothing headphone (1)", "headphone (1)"), "3500"),
    Model("B171", "Nothing Ear", ("nothing ear",)),
    Model("B172", "CMF Buds Pro 2", ("cmf buds pro 2", "cmf bud pro 2"), "6900"),
    Model("B187", "CMF Buds Pro 2", ("cmf buds pro 2",), "6900"),
    Model("B163", "CMF Buds Pro", ("cmf buds pro",)),
    Model("B184", "CMF Buds 2 Plus", ("cmf buds 2 plus", "cmf buds2 plus"), "6900"),
    Model("B185", "CMF Buds 2a", ("cmf buds 2a",), "6900"),
    Model("B179", "CMF Buds 2", ("cmf buds 2",), "6900"),
    Model("B193", "CMF Buds Neo", ("cmf buds neo",)),
    Model("B168", "CMF Buds", ("cmf buds",), "6900"),
    Model("B164", "CMF Neckband Pro", ("cmf neckband pro", "neckband pro"), "6900"),
    Model("B175", "CMF Headphone Pro", ("cmf headphone pro",), "3500"),
    Model("B189", "CMF Clip Pro", ("cmf clip pro",)),
)


def match_model(name: str) -> Model | None:
    folded = " ".join(name.casefold().split())
    for model in MODELS:
        if any(alias in folded for alias in model.aliases):
            return model
    return None


def looks_like_earbud(name: str, address: str) -> bool:
    if match_model(name) is not None:
        return True
    prefix = address.upper()[:8]
    return prefix in MAC_PREFIXES
