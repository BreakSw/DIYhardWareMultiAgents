from __future__ import annotations

from decimal import Decimal
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.knowledge.http import redact_secrets


FEATURE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "cpu": {
        "socket": ("sockettype", "cpusocket", "processorsocket"),
        "cores": ("numberofcores", "cpucores", "corecount"),
        "threads": ("numberofthreads", "cputhreads", "threadcount"),
        "base_clock": ("clockspeed", "baseclockspeed", "baseclock"),
        "boost_clock": (
            "boostclockspeed",
            "maxboostclock",
            "maximumboostclock",
        ),
        "tdp_w": (
            "thermaldesignpowertdp",
            "thermaldesignpower",
            "cputdp",
        ),
        "memory_types": (
            "memorytype",
            "ramtype",
            "supportedmemory",
            "supportedmemorytype",
        ),
        "pcie_version": (
            "expansionslottype",
            "pcieslots",
            "pcieversion",
            "pciexpressversion",
            "interface",
        ),
    },
    "gpu": {
        "chipset": ("gpuchipset", "chipsetmodel", "gpumodel"),
        "vram_gb": (
            "videomemory",
            "gpuvideomemory",
            "memorysize",
            "vram",
        ),
        "memory_type": (
            "videomemorytype",
            "gpuvideomemorytype",
            "memorytype",
        ),
        "tdp_w": (
            "thermaldesignpowertdp",
            "thermaldesignpower",
            "gputdp",
        ),
        "length_mm": ("gpulength", "length", "cardlength"),
        "power_connectors": (
            "powerconnectors",
            "gpupowerconnectors",
            "powerconnector",
        ),
        "recommended_psu_w": (
            "gpurecommendedpsu",
            "recommendedpsu",
            "recommendedpowersupply",
        ),
    },
    "motherboard": {
        "socket": (
            "sockettype",
            "cpusocket",
            "processorsocket",
            "processorsockettype",
        ),
        "chipset": ("motherboardchipset", "chipsettype"),
        "form_factor": (
            "formfactor",
            "motherboardformfactor",
            "boardformfactor",
        ),
        "memory_type": (
            "memorytype",
            "ramtype",
            "supportedmemory",
            "supportedmemorytype",
            "memorytechnology",
        ),
        "memory_slots": (
            "memoryslots",
            "numberofmemoryslots",
            "dimmslots",
            "numberofdimmslots",
        ),
        "max_memory_gb": (
            "maxmemory",
            "maximummemory",
            "maxmemorycapacity",
            "maximummemorycapacity",
        ),
        "pcie_slots": (
            "pcieslots",
            "pciexpressslots",
            "expansionslots",
            "expansionslottype",
        ),
        "m2_slots": (
            "m2slots",
            "numberofm2slots",
            "m2socket",
            "m2sockets",
        ),
    },
    "memory": {
        "memory_type": (
            "type",
            "memorytype",
            "ramtype",
            "memorytechnology",
            "ddrtype",
        ),
        "total_capacity_gb": (
            "capacity",
            "totalcapacity",
            "memorycapacity",
            "kitsize",
        ),
        "module_count": (
            "modulecount",
            "numberofmodules",
            "kitconfiguration",
            "modules",
        ),
        "speed_mt_s": (
            "speed",
            "memoryspeed",
            "dataspeed",
            "transferspeed",
            "speedrating",
        ),
        "cas_latency": ("caslatency", "cltiming", "latency"),
        "voltage": (
            "voltage",
            "operatingvoltage",
            "testedvoltage",
        ),
    },
    "storage": {
        "capacity_gb": (
            "capacity",
            "storagecapacity",
            "digitalstoragecapacity",
            "drivecapacity",
        ),
        "form_factor": (
            "formfactor",
            "driveformfactor",
            "harddriveformfactor",
        ),
        "interface": (
            "interface",
            "hardwareinterface",
            "businterface",
            "driveinterface",
        ),
        "protocol": (
            "protocol",
            "transferprotocol",
            "storageprotocol",
            "nvmeversion",
        ),
        "sequential_read_mb_s": (
            "sequentialreadspeed",
            "maximumsequentialread",
            "maxsequentialread",
            "sequentialread",
            "readperformance",
        ),
        "sequential_write_mb_s": (
            "sequentialwritespeed",
            "maximumsequentialwrite",
            "maxsequentialwrite",
            "sequentialwrite",
            "writeperformance",
        ),
        "endurance_tbw": (
            "endurance",
            "terabyteswritten",
            "writedurability",
            "ratedendurance",
        ),
    },
    "psu": {
        "wattage_w": (
            "outputwattage",
            "continuouspower",
            "peakpower",
            "wattage",
        ),
        "efficiency_rating": (
            "80plusrating",
            "efficiency",
            "efficiencyrating",
        ),
        "form_factor": ("formfactor", "psuformfactor"),
        "atx_version": ("supportedstandards", "atxversion"),
        "modular_type": ("modular", "modulartype", "cablingtype"),
        "pcie_connectors": (
            "connectors",
            "cables",
            "pcieconnectors",
        ),
    },
    "cooler": {
        "cooler_type": ("coolingtype", "coolertype"),
        "supported_sockets": (
            "socketcompatibility",
            "supportedsockets",
            "cpusocket",
        ),
        "fan_count": ("includedfans", "fancount", "numberoffans"),
        "height_mm": ("height", "coolerheight"),
        "radiator_size_mm": (
            "radiatorsupport",
            "fanmountsize",
            "radiatorsize",
        ),
        "rated_tdp_w": (
            "coolingtdp",
            "coolingcapacity",
            "ratedtdp",
        ),
        "supported_processor_range": (
            "supportedprocessorrange",
            "supportedprocessors",
        ),
    },
    "case": {
        "supported_motherboard_form_factors": (
            "motherboardformfactor",
            "supportedmotherboardformfactors",
            "motherboardcompatibility",
        ),
        "max_gpu_length_mm": (
            "maximumgpulength",
            "gpulengthsupport",
            "maxgpulength",
        ),
        "max_cooler_height_mm": (
            "maximumcpucoolerheight",
            "cpucoolerheightsupport",
            "maxcoolerheight",
        ),
        "supported_radiators": (
            "radiatorsupport",
            "supportedradiators",
        ),
        "psu_form_factor": ("psuformfactor", "powersupplyformfactor"),
        "drive_bays": (
            "drivebaycount",
            "maxstoragedrivecount",
            "maximumstoragedrivecount",
            "drivebays",
        ),
    },
}

_MILLIMETER_FIELDS = {
    "length_mm",
    "height_mm",
    "radiator_size_mm",
    "max_gpu_length_mm",
    "max_cooler_height_mm",
}
_GIGABYTE_FIELDS = {
    "vram_gb",
    "max_memory_gb",
    "total_capacity_gb",
    "capacity_gb",
}
_THROUGHPUT_FIELDS = {
    "sequential_read_mb_s",
    "sequential_write_mb_s",
}
_RELEASE_DATE_ALIASES = (
    "releasedate",
    "cpureleasedate",
    "gpureleasedate",
    "productreleasedate",
)
_COMPOSITE_MISSING_FIELDS: dict[str, set[str]] = {
    "height_mm_or_radiator_size_mm": {
        "height_mm",
        "radiator_size_mm",
    },
    "rated_tdp_w_or_supported_processor_range": {
        "rated_tdp_w",
        "supported_processor_range",
    },
}
_FOLLOW_UP_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "socket": ("cpu socket", "processor socket"),
    "cores": ("cpu cores", "core count", "number of cores"),
    "threads": ("cpu threads", "thread count", "number of threads"),
    "base_clock": ("base clock speed",),
    "boost_clock": ("boost clock speed", "max boost clock"),
    "tdp_w": ("tdp", "thermal design power"),
    "memory_types": ("memory type", "ram type", "supported memory"),
    "pcie_version": ("pcie version", "pci express version"),
    "vram_gb": ("video memory", "vram"),
    "memory_type": (
        "memory type",
        "ram type",
        "video memory type",
        "ddr type",
    ),
    "length_mm": ("gpu length", "card length"),
    "power_connectors": ("gpu power connectors",),
    "recommended_psu_w": ("recommended psu",),
    "form_factor": (
        "motherboard form factor",
        "drive form factor",
        "psu form factor",
    ),
    "memory_slots": ("dimm slots", "number of memory slots"),
    "max_memory_gb": ("maximum memory", "max memory capacity"),
    "pcie_slots": ("pci express slots",),
    "m2_slots": ("m.2 slots", "m2 sockets"),
    "total_capacity_gb": ("total capacity", "memory capacity", "kit size"),
    "module_count": ("number of modules", "kit configuration"),
    "speed_mt_s": ("memory speed", "transfer speed"),
    "cas_latency": ("cas latency", "cl timing"),
    "capacity_gb": ("storage capacity", "drive capacity"),
    "interface": ("hardware interface", "drive interface"),
    "protocol": ("storage protocol", "transfer protocol"),
    "sequential_read_mb_s": ("sequential read speed",),
    "sequential_write_mb_s": ("sequential write speed",),
    "endurance_tbw": ("rated endurance", "terabytes written"),
    "wattage_w": ("output wattage", "continuous power"),
    "efficiency_rating": ("80 plus rating", "efficiency rating"),
    "atx_version": ("atx version",),
    "modular_type": ("modular type", "cabling type"),
    "pcie_connectors": ("pcie connectors",),
    "cooler_type": ("cooler type", "cooling type"),
    "supported_sockets": ("supported sockets", "socket compatibility"),
    "fan_count": ("fan count", "number of fans"),
    "height_mm": ("cooler height",),
    "radiator_size_mm": ("radiator size",),
    "rated_tdp_w": ("rated tdp", "cooling tdp"),
    "supported_processor_range": (
        "supported processor range",
        "supported processors",
    ),
    "supported_motherboard_form_factors": (
        "supported motherboard form factors",
        "motherboard compatibility",
    ),
    "max_gpu_length_mm": ("maximum gpu length", "max gpu length"),
    "max_cooler_height_mm": (
        "maximum cpu cooler height",
        "max cooler height",
    ),
    "supported_radiators": ("supported radiators", "radiator support"),
    "psu_form_factor": ("power supply form factor",),
    "drive_bays": ("drive bay count", "maximum storage drive count"),
}


def normalize_feature_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def sanitize_source_url(
    value: Any,
    secrets: list[str] | None = None,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if (
        parts.scheme.lower() not in {"http", "https"}
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
    ):
        return None
    without_fragment = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, "")
    )
    return str(redact_secrets(without_fragment, secrets))


def _normalize_follow_up_value(
    category: str,
    field: str,
    value: Any,
) -> str | None:
    if isinstance(value, (dict, list, tuple)):
        return None
    text = str(value).strip()
    if not text or text.casefold() in {
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "not available",
    }:
        return None
    if field in {"memory_type", "memory_types"}:
        memory_patterns = {
            ("gpu", "memory_type"): r"\bGDDR[3-7]\b",
            ("motherboard", "memory_type"): r"\b(?:LP)?DDR[3-6]\b",
            ("memory", "memory_type"): r"\b(?:LP)?DDR[3-6]\b",
            ("cpu", "memory_types"): r"\b(?:LP)?DDR[3-6]\b",
        }
        pattern = memory_patterns.get((category, field))
        if pattern is None:
            return None
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(0).upper() if match else None

    quantity_patterns = {
        "length_mm": r"\d(?:[\d,.]*\d)?\s*(?:mm|cm|inches?|in|\")",
        "height_mm": r"\d(?:[\d,.]*\d)?\s*(?:mm|cm|inches?|in|\")",
        "radiator_size_mm": r"\d(?:[\d,.]*\d)?\s*(?:mm|cm|inches?|in|\")",
        "max_gpu_length_mm": r"\d(?:[\d,.]*\d)?\s*(?:mm|cm|inches?|in|\")",
        "max_cooler_height_mm": r"\d(?:[\d,.]*\d)?\s*(?:mm|cm|inches?|in|\")",
        "vram_gb": r"\d(?:[\d,.]*\d)?\s*(?:GB|TB)\b",
        "max_memory_gb": r"\d(?:[\d,.]*\d)?\s*(?:GB|TB)\b",
        "total_capacity_gb": r"\d(?:[\d,.]*\d)?\s*(?:GB|TB)\b",
        "capacity_gb": r"\d(?:[\d,.]*\d)?\s*(?:GB|TB)\b",
        "base_clock": r"\d(?:[\d,.]*\d)?\s*(?:GHz|MHz)\b",
        "boost_clock": r"\d(?:[\d,.]*\d)?\s*(?:GHz|MHz)\b",
        "tdp_w": r"\d(?:[\d,.]*\d)?\s*W\b",
        "recommended_psu_w": r"\d(?:[\d,.]*\d)?\s*W\b",
        "wattage_w": r"\d(?:[\d,.]*\d)?\s*W\b",
        "rated_tdp_w": r"\d(?:[\d,.]*\d)?\s*W\b",
        "speed_mt_s": r"(?:\d(?:[\d,.]*\d)?\s*(?:MT/s|MTs|MHz)\b|^\d[\d,]*$)",
        "sequential_read_mb_s": r"\d(?:[\d,.]*\d)?\s*(?:MB/s|GB/s)\b",
        "sequential_write_mb_s": r"\d(?:[\d,.]*\d)?\s*(?:MB/s|GB/s)\b",
        "endurance_tbw": r"\d(?:[\d,.]*\d)?\s*(?:TBW|PBW)\b",
        "voltage": r"\d(?:[\d,.]*\d)?\s*V\b",
        "cas_latency": r"CL\s*-?\s*\d+",
    }
    pattern = quantity_patterns.get(field)
    if pattern is not None:
        return text if re.fullmatch(pattern, text, re.IGNORECASE) else None

    if field in {
        "cores",
        "threads",
        "memory_slots",
        "pcie_slots",
        "m2_slots",
        "fan_count",
        "drive_bays",
    }:
        return text if re.fullmatch(r"\d+(?:\s+(?:slots?|fans?|bays?))?", text, re.IGNORECASE) else None
    if field == "module_count":
        return text if re.fullmatch(
            r"(?:\d+|\d+\s*[xX\u00d7]\s*\d+(?:[\d,.]*\d)?\s*(?:GB|TB))",
            text,
            re.IGNORECASE,
        ) else None

    socket = r"(?:LGA\s*\d{3,4}|AM\d|FM\d|sTRX\d|TR\d|SP\d)"
    motherboard_form_factor = (
        r"(?:E-?ATX|ATX|Micro[-\s]?ATX|mATX|Mini[-\s]?ITX)"
    )
    drive_form_factor = r"(?:M\.?2(?:\s+22\d{2})?|[23]\.5[-\s]?(?:inch|in))"
    psu_form_factor = r"(?:ATX|SFX(?:-L)?|TFX|Flex\s*ATX)"
    if field == "form_factor":
        category_pattern = {
            "motherboard": motherboard_form_factor,
            "storage": drive_form_factor,
            "psu": psu_form_factor,
        }.get(category)
        if category_pattern is None:
            return None
        return text if re.fullmatch(
            category_pattern,
            text,
            re.IGNORECASE,
        ) else None
    connector = r"(?=.*(?:pin|PCIe|12VHPWR|12V-2x6))[A-Za-z0-9 +xX,./-]+"
    strict_patterns = {
        "socket": socket,
        "supported_sockets": rf"{socket}(?:\s*[,/;+]\s*{socket})*",
        "chipset": r"(?=.*\d)[A-Za-z0-9][A-Za-z0-9 +.-]{1,60}",
        "psu_form_factor": psu_form_factor,
        "supported_motherboard_form_factors": rf"{motherboard_form_factor}(?:\s*[,/;+]\s*{motherboard_form_factor})*",
        "pcie_version": r"(?:(?:PCIe?|PCI Express)\s*)?\d(?:\.\d)?",
        "interface": r"(?:(?:PCIe?|PCI Express)\s*\d(?:\.\d)?(?:\s*x\d+)?|SATA(?:\s*III)?|USB\s*\d(?:\.\d)?(?:\s*Gen\s*\d(?:x\d)?)?)",
        "protocol": r"(?:NVMe(?:\s*\d(?:\.\d)?)?|SATA(?:\s*III)?|AHCI)",
        "power_connectors": connector,
        "pcie_connectors": connector,
        "efficiency_rating": r"80\s*PLUS\s*(?:White|Bronze|Silver|Gold|Platinum|Titanium)",
        "atx_version": r"ATX\s*\d(?:\.\d)?",
        "modular_type": r"(?:Non[-\s]?Modular|Semi[-\s]?Modular|Fully\s+Modular|Full[-\s]?Modular)",
        "cooler_type": r"(?:Air|Liquid|AIO|All[-\s]?in[-\s]?One)(?:\s+Cooler|\s+Cooling)?",
        "supported_radiators": r"\d{2,3}\s*mm(?:\s*[,/;+]\s*\d{2,3}\s*mm)*",
        "supported_processor_range": r"(?=.*(?:Intel\s+Core|AMD\s+Ryzen|Threadripper|Xeon))[A-Za-z0-9 +./-]{3,100}",
    }
    pattern = strict_patterns.get(field)
    if pattern is None:
        return None
    return text if re.fullmatch(pattern, text, re.IGNORECASE) else None


def _feature_map(features: Any) -> dict[str, Any]:
    if not isinstance(features, list):
        return {}
    mapped: dict[str, Any] = {}
    for item in features:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        key = normalize_feature_key(str(item.get("title") or ""))
        if key:
            mapped.setdefault(key, value)
    return mapped


def _pick_feature(
    features: dict[str, Any],
    field: str,
    aliases: tuple[str, ...],
) -> Any:
    for alias in (normalize_feature_key(field), *aliases):
        if alias in features:
            return features[alias]
    return None


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _converted_quantity(
    value: Any,
    units: dict[str, Decimal],
) -> Any:
    if value in (None, ""):
        return value
    text = str(value).strip()
    unit_pattern = "|".join(
        sorted((re.escape(unit) for unit in units), key=len, reverse=True)
    )
    match = re.search(
        rf"(\d[\d,]*(?:\.\d+)?)\s*({unit_pattern})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text
    amount = Decimal(match.group(1).replace(",", ""))
    factor = units[match.group(2).lower()]
    return _decimal_text(amount * factor)


def _millimeters(value: Any) -> Any:
    if value in (None, ""):
        return value
    text = str(value).strip()
    match = re.search(
        r"(\d[\d,]*(?:\.\d+)?)\s*"
        r"((?:mm|millimeters?|cm|centimeters?|inches?|in)\b|\")",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text
    amount = Decimal(match.group(1).replace(",", ""))
    unit = match.group(2).lower()
    if unit.startswith("cm") or unit.startswith("centimeter"):
        amount *= Decimal("10")
    elif unit in {"in", "inch", "inches", '"'}:
        amount *= Decimal("25.4")
    return _decimal_text(amount.quantize(Decimal("0.1")))


def _gigabytes(value: Any) -> Any:
    return _converted_quantity(
        value,
        {"gb": Decimal("1"), "tb": Decimal("1000")},
    )


def _megabytes_per_second(value: Any) -> Any:
    if value in (None, ""):
        return value
    text = str(value).strip()
    match = re.search(
        r"(\d[\d,]*(?:\.\d+)?)\s*(GB/s|MB/s)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text
    amount = Decimal(match.group(1).replace(",", ""))
    if match.group(2).lower() == "gb/s":
        amount *= Decimal("1000")
    return _decimal_text(amount)


def _terabytes_written(value: Any) -> Any:
    return _converted_quantity(
        value,
        {"tbw": Decimal("1"), "pbw": Decimal("1000")},
    )


def _memory_speed(value: Any) -> Any:
    if value in (None, ""):
        return value
    text = str(value).strip()
    match = re.search(
        r"(\d[\d,]*(?:\.\d+)?)\s*(?:MT/s|MTs|MHz)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return _decimal_text(Decimal(match.group(1).replace(",", "")))
    if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", text):
        return text.replace(",", "")
    return text


def _module_count(value: Any) -> Any:
    if value in (None, ""):
        return value
    text = str(value).strip()
    match = re.search(r"\b(\d+)\s*[xX\u00d7]\s*\d", text)
    if match:
        return match.group(1)
    return text


def _cas_latency(value: Any) -> Any:
    if value in (None, ""):
        return value
    text = str(value).strip()
    match = re.search(r"\bCL\s*-?\s*(\d+)\b", text, re.IGNORECASE)
    return f"CL{match.group(1)}" if match else text


def _set_match(
    specs: dict[str, Any],
    field: str,
    text: str,
    pattern: str,
    *,
    group: int = 0,
    flags: int = re.IGNORECASE,
) -> None:
    if specs.get(field) not in (None, ""):
        return
    match = re.search(pattern, text, flags)
    if match:
        specs[field] = match.group(group).strip()


def _supplement_cpu(specs: dict[str, Any], text: str) -> None:
    if specs.get("pcie_version") in (None, ""):
        match = re.search(r"\bPCIe?\s*(\d(?:\.\d)?)\b", text, re.IGNORECASE)
        if match:
            specs["pcie_version"] = f"PCIe {match.group(1)}"


def _supplement_gpu(specs: dict[str, Any], text: str) -> None:
    if specs.get("vram_gb") not in (None, ""):
        return
    match = re.search(
        r"(?:^|[-\s])(?:O|OC)?(\d{1,2})G(?:B)?(?:[-\s]|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        specs["vram_gb"] = match.group(1)


def _supplement_motherboard(specs: dict[str, Any], text: str) -> None:
    _set_match(
        specs,
        "socket",
        text,
        r"\b(?:LGA\s*\d{3,4}|AM\d|sTRX\d|TR\d)\b",
    )
    _set_match(specs, "memory_type", text, r"\b(?:LP)?DDR[3-6]\b")
    _set_match(
        specs,
        "form_factor",
        text,
        r"\b(?:E-?ATX|Micro[-\s]?ATX|mATX|Mini[-\s]?ITX|ATX)\b",
    )
    _set_match(
        specs,
        "memory_slots",
        text,
        r"\b(\d+)\s*(?:DIMM|memory)\s+slots?\b",
        group=1,
    )


def _supplement_memory(specs: dict[str, Any], text: str) -> None:
    _set_match(specs, "memory_type", text, r"\b(?:LP)?DDR[3-6]\b")
    module_match = re.search(
        r"\b(?P<count>\d+)\s*[xX\u00d7]\s*"
        r"(?P<capacity>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?P<unit>TB|GB)\b",
        text,
        re.IGNORECASE,
    )
    if specs.get("module_count") in (None, "") and module_match:
        specs["module_count"] = module_match.group("count")
    if specs.get("total_capacity_gb") in (None, ""):
        capacity_match = re.search(
            r"\b(\d[\d,]*(?:\.\d+)?\s*(?:TB|GB))\b",
            text,
            re.IGNORECASE,
        )
        has_explicit_capacity = (
            capacity_match is not None
            and (
                module_match is None
                or capacity_match.start() < module_match.start()
            )
        )
        if has_explicit_capacity and capacity_match is not None:
            specs["total_capacity_gb"] = capacity_match.group(1)
        elif module_match is not None:
            count = Decimal(module_match.group("count"))
            capacity = Decimal(
                module_match.group("capacity").replace(",", "")
            )
            specs["total_capacity_gb"] = (
                f"{_decimal_text(count * capacity)} "
                f"{module_match.group('unit')}"
            )
        elif capacity_match is not None:
            specs["total_capacity_gb"] = capacity_match.group(1)
    _set_match(
        specs,
        "speed_mt_s",
        text,
        r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:MT/s|MTs|MHz)\b",
        group=1,
    )
    _set_match(
        specs,
        "cas_latency",
        text,
        r"\b(CL\s*-?\s*\d+)\b",
        group=1,
    )
    _set_match(
        specs,
        "voltage",
        text,
        r"\b(\d+(?:\.\d+)?\s*V)\b",
        group=1,
    )


def _supplement_storage(specs: dict[str, Any], text: str) -> None:
    _set_match(
        specs,
        "capacity_gb",
        text,
        r"\b(\d[\d,]*(?:\.\d+)?\s*(?:TB|GB))\b(?!\s*/\s*s\b)",
        group=1,
    )
    _set_match(
        specs,
        "form_factor",
        text,
        r"\b(M\.?2(?:\s+22\d{2})?|[23]\.5[-\s]?(?:inch|in))\b",
        group=1,
    )
    _set_match(
        specs,
        "interface",
        text,
        r"\b((?:PCIe?|PCI Express)\s*\d(?:\.\d)?(?:\s*x\d+)?)\b",
        group=1,
    )
    _set_match(
        specs,
        "protocol",
        text,
        r"\b(NVMe(?:\s*\d(?:\.\d)?)?|SATA(?:\s*III)?)\b",
        group=1,
    )


def _supplement_psu(specs: dict[str, Any], text: str) -> None:
    _set_match(
        specs,
        "wattage_w",
        text,
        r"\b(\d[\d,]*(?:\.\d+)?\s*W)\b",
        group=1,
    )
    _set_match(
        specs,
        "efficiency_rating",
        text,
        r"\b(80\s*PLUS\s*(?:White|Bronze|Silver|Gold|Platinum|Titanium))\b",
        group=1,
    )


def _supplement_specs(
    category: str,
    specs: dict[str, Any],
    title: str,
    description: str,
) -> None:
    text = " ".join(part for part in (title, description) if part)
    if not text:
        return
    supplements = {
        "cpu": _supplement_cpu,
        "gpu": _supplement_gpu,
        "motherboard": _supplement_motherboard,
        "memory": _supplement_memory,
        "storage": _supplement_storage,
        "psu": _supplement_psu,
    }
    supplement = supplements.get(category)
    if supplement is not None:
        supplement(specs, text)


def _convert_units(category: str, specs: dict[str, Any]) -> None:
    for field in _MILLIMETER_FIELDS & specs.keys():
        specs[field] = _millimeters(specs[field])
    for field in _GIGABYTE_FIELDS & specs.keys():
        specs[field] = _gigabytes(specs[field])
    for field in _THROUGHPUT_FIELDS & specs.keys():
        specs[field] = _megabytes_per_second(specs[field])
    if "endurance_tbw" in specs:
        specs["endurance_tbw"] = _terabytes_written(
            specs["endurance_tbw"]
        )
    if category == "memory":
        if "module_count" in specs:
            specs["module_count"] = _module_count(specs["module_count"])
        if "speed_mt_s" in specs:
            specs["speed_mt_s"] = _memory_speed(specs["speed_mt_s"])
        if "cas_latency" in specs:
            specs["cas_latency"] = _cas_latency(specs["cas_latency"])


def normalize_specs(
    category: str,
    features: Any,
    *,
    title: str = "",
    description: str = "",
) -> dict[str, Any]:
    aliases = FEATURE_ALIASES.get(category)
    if aliases is None:
        return {}
    mapped_features = _feature_map(features)
    specs = {
        field: _pick_feature(mapped_features, field, names)
        for field, names in aliases.items()
    }
    _supplement_specs(category, specs, title, description)
    _convert_units(category, specs)
    return {
        field: value
        for field, value in specs.items()
        if value not in (None, "")
    }


def extract_search_specs(
    category: str,
    missing_fields: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    snippets: list[str] = []
    category_aliases = FEATURE_ALIASES.get(category, {})
    follow_up_labels = {
        normalize_feature_key(label): field
        for field in category_aliases
        for label in (field, *_FOLLOW_UP_LABEL_ALIASES.get(field, ()))
    }
    canonical_labels = {
        normalize_feature_key(field): field for field in category_aliases
    }

    def append_feature(
        title: Any,
        value: Any,
        allowed_labels: dict[str, str],
    ) -> None:
        if (
            title in (None, "")
            or value in (None, "")
            or isinstance(title, (dict, list))
            or isinstance(value, (dict, list))
        ):
            return
        field = allowed_labels.get(normalize_feature_key(str(title)))
        normalized = (
            _normalize_follow_up_value(category, field, value)
            if field is not None
            else None
        )
        if field is not None and normalized is not None:
            features.append({"title": field, "value": normalized})

    def append_root_fields(section: Any) -> None:
        if not isinstance(section, dict):
            return
        for key, value in section.items():
            append_feature(key, value, canonical_labels)

    def append_table_rows(table: Any) -> None:
        if not isinstance(table, list):
            return
        for row in table:
            if isinstance(row, (list, tuple)) and len(row) == 2:
                append_feature(row[0], row[1], follow_up_labels)

    organic_results = payload.get("organic_results")
    if isinstance(organic_results, list):
        for result in organic_results:
            if not isinstance(result, dict):
                continue
            snippet = result.get("snippet")
            if isinstance(snippet, str) and snippet.strip():
                snippets.append(snippet.strip())

    answer_box = payload.get("answer_box")
    append_root_fields(answer_box)
    if isinstance(answer_box, dict):
        append_table_rows(answer_box.get("table"))
        contents = answer_box.get("contents")
        if isinstance(contents, dict):
            append_table_rows(contents.get("table"))

    append_root_fields(payload.get("knowledge_graph"))

    explicit_pair = re.compile(
        r"^\s*([A-Za-z][A-Za-z0-9 _/()+.-]{1,60})"
        r"\s*[:=]\s*(\S(?:.*\S)?)\s*$"
    )
    for text in snippets:
        for segment in re.split(r"[;\n|]+", text):
            match = explicit_pair.match(segment)
            if match:
                append_feature(
                    match.group(1),
                    match.group(2),
                    follow_up_labels,
                )

    specs = normalize_specs(category, features)
    requested = set(missing_fields)
    allowed = set(requested)
    for field in requested:
        allowed.update(_COMPOSITE_MISSING_FIELDS.get(field, set()))
    return {
        field: value
        for field, value in specs.items()
        if field in allowed
    }


def extract_release_date(features: Any) -> Any:
    mapped_features = _feature_map(features)
    for alias in _RELEASE_DATE_ALIASES:
        if alias in mapped_features:
            return mapped_features[alias]
    return None
