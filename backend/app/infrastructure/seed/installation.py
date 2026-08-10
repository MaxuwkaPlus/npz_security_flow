"""Каталог установки ЭЛОУ-АВТ, версия 1.

Границы параметров демонстрационные (`provisional`): регламентными считаются только
значения, прямо названные в `docs/TRAINER_SCENARIO.md` — 140 °C после Т-1…Т-11,
блокировка электродегидратора при уровне ниже 3500 мм, вода 5–10 % от расхода нефти,
низ К-1 до 280 °C, верх К-2 до 148 °C и низ К-2 до 350 °C.

Коды оборудования записаны латиницей (`T-4/1`, `E-3`, `K-1`), подпись на мнемосхеме —
кириллицей. Коды тегов совпадают с именами полей snapshot.
"""

from itertools import pairwise

from app.infrastructure.seed.specs import EdgeSpec, EquipmentSpec, InstallationSpec, TagSpec

INSTALLATION_CODE = "ELOU-AVT"
INSTALLATION_VERSION = 1

NOMINAL_BRANCH_FLOW_TPH = 100.0
T11_TEMPERATURE_LIMIT_C = 140.0
ELOU_LOW_LEVEL_INTERLOCK_MM = 3500.0

# Три параллельные сырьевые ветви и их цепочки предварительного подогрева (сценарий, §46).
BRANCH_CONTROLLERS = {1: "FRC-404", 2: "FRC-405", 3: "FRC-406"}
BRANCH_CHAINS: dict[int, tuple[str, ...]] = {
    1: ("T-1/1", "T-1/2", "T-1/3", "T-2", "T-3/1", "T-3/2"),
    2: ("T-4/1", "T-4/2", "T-5", "T-6/1", "T-6/2", "T-7/1"),
    3: ("T-7/2", "T-8", "T-9/1", "T-9/2", "T-10/1", "T-10/2", "T-11"),
}

# Е-15 и Э-1…Э-6 в кириллице различаются, в латинице — нет, поэтому ёмкость кодируется V-15.
CYRILLIC_PREFIX = {"T": "Т", "E": "Э", "K": "К", "N": "Н", "A": "А", "P": "П", "CO": "ЦО", "V": "Е"}


def display_name(code: str) -> str:
    prefix, separator, rest = code.partition("-")
    return f"{CYRILLIC_PREFIX.get(prefix, prefix)}{separator}{rest}"


def branch_controller_tags(branch_no: int) -> tuple[TagSpec, ...]:
    return (
        TagSpec(
            f"branch_{branch_no}_flow_tph",
            "t/h",
            normal_min=95.0,
            normal_max=105.0,
            warning_min=92.0,
            warning_max=108.0,
            critical_min=88.0,
        ),
        TagSpec(
            f"branch_{branch_no}_pressure_bar",
            "bar",
            normal_min=4.6,
            normal_max=5.4,
            warning_min=4.3,
            critical_min=4.0,
        ),
        TagSpec(f"branch_{branch_no}_valve_command_pct", "%", normal_min=0.0, normal_max=100.0),
        TagSpec(f"branch_{branch_no}_valve_actual_pct", "%", normal_min=0.0, normal_max=100.0),
    )


def branch_outlet_tag(branch_no: int) -> TagSpec:
    """Температура ветви после всей цепочки Т-1…Т-11; ограничение регламента — 140 °C."""

    return TagSpec(
        f"branch_{branch_no}_t11_outlet_temp_c",
        "degC",
        normal_max=T11_TEMPERATURE_LIMIT_C,
        warning_max=T11_TEMPERATURE_LIMIT_C,
        critical_max=144.0,
    )


def heat_exchanger_equipment() -> list[EquipmentSpec]:
    equipment: list[EquipmentSpec] = []
    for branch_no, chain in BRANCH_CHAINS.items():
        for position, code in enumerate(chain, start=1):
            is_last = position == len(chain)
            equipment.append(
                EquipmentSpec(
                    code=code,
                    equipment_type="heat_exchanger",
                    display_name=display_name(code),
                    tags=(branch_outlet_tag(branch_no),) if is_last else (),
                    metadata={"branch_no": branch_no, "position": position},
                )
            )
    return equipment


FEED_EQUIPMENT = [
    EquipmentSpec("TANK-FARM", "tank_farm", "Резервуарный парк"),
    EquipmentSpec(
        "FEED-SYSTEM",
        "unit_section",
        "Сырьевая часть",
        tags=(
            TagSpec("total_feed_flow_tph", "t/h", normal_min=285.0, normal_max=315.0, critical_min=265.0),
            TagSpec("min_branch_flow_ratio", "ratio", normal_min=0.95, warning_min=0.92, critical_min=0.88),
            TagSpec("flow_imbalance_ratio", "ratio", normal_max=0.05, warning_max=0.12, critical_max=0.20),
            TagSpec("lowest_flow_branch_code", "-", value_type="int"),
        ),
    ),
    EquipmentSpec(
        "N-1",
        "feed_pump",
        "Сырьевой насос Н-1",
        tags=(
            TagSpec(
                "feed_pump_discharge_pressure_bar",
                "bar",
                normal_min=5.5,
                normal_max=6.5,
                warning_min=5.2,
                critical_min=4.8,
            ),
            TagSpec("feed_pump_state", "-", value_type="enum"),
        ),
        metadata={"role": "working"},
    ),
    EquipmentSpec(
        "N-1A",
        "feed_pump",
        "Сырьевой насос Н-1А",
        tags=(TagSpec("standby_pump_state", "-", value_type="enum"),),
        metadata={"role": "standby"},
    ),
    EquipmentSpec("N-1B", "feed_pump", "Сырьевой насос Н-1Б", metadata={"modeled": False}),
    EquipmentSpec("N-1V", "feed_pump", "Сырьевой насос Н-1В", metadata={"modeled": False}),
]

ELOU_EQUIPMENT = [
    EquipmentSpec(
        "ELOU",
        "unit_section",
        "Блок ЭЛОУ",
        tags=(
            # Подача воды 5–10 % от расхода сырой нефти (сценарий, §23).
            TagSpec("elou_wash_water_ratio", "ratio", normal_min=0.05, normal_max=0.10),
            TagSpec(
                "elou_stage1_min_level_mm",
                "mm",
                normal_min=3700.0,
                warning_min=3600.0,
                critical_min=ELOU_LOW_LEVEL_INTERLOCK_MM,
            ),
            TagSpec(
                "elou_stage2_min_level_mm",
                "mm",
                normal_min=3700.0,
                warning_min=3600.0,
                critical_min=ELOU_LOW_LEVEL_INTERLOCK_MM,
            ),
            TagSpec("elou_temperature_c", "degC", normal_min=110.0, normal_max=140.0),
            TagSpec(
                "elou_load_imbalance_ratio", "ratio", normal_max=0.10, warning_max=0.18, critical_max=0.28
            ),
            TagSpec("elou_hv_trip_count", "count", value_type="int", normal_max=0.0, critical_max=0.0),
        ),
    ),
    EquipmentSpec("A-19", "mixer", "Смеситель А-19", parent_code="ELOU"),
    EquipmentSpec("E-1", "electric_dehydrator", "Э-1", parent_code="ELOU", metadata={"stage": 1}),
    EquipmentSpec("E-3", "electric_dehydrator", "Э-3", parent_code="ELOU", metadata={"stage": 1}),
    EquipmentSpec("E-5", "electric_dehydrator", "Э-5", parent_code="ELOU", metadata={"stage": 1}),
    EquipmentSpec("A-20", "mixer", "Смеситель А-20", parent_code="ELOU"),
    EquipmentSpec("E-2", "electric_dehydrator", "Э-2", parent_code="ELOU", metadata={"stage": 2}),
    EquipmentSpec("E-4", "electric_dehydrator", "Э-4", parent_code="ELOU", metadata={"stage": 2}),
    EquipmentSpec("E-6", "electric_dehydrator", "Э-6", parent_code="ELOU", metadata={"stage": 2}),
]

ATMOSPHERIC_EQUIPMENT = [
    EquipmentSpec(
        "V-15",
        "vessel",
        "Ёмкость Е-15",
        tags=(TagSpec("e15_level_pct", "%", normal_min=40.0, normal_max=60.0, critical_min=20.0),),
    ),
    EquipmentSpec("N-20", "pump", "Насос Н-20", tags=(TagSpec("n20_state", "-", value_type="enum"),)),
    EquipmentSpec("N-20A", "pump", "Насос Н-20А", metadata={"role": "standby"}),
    EquipmentSpec("N-20B", "pump", "Насос Н-20Б", metadata={"role": "standby"}),
    EquipmentSpec(
        "T-17_T-27",
        "heat_exchanger_group",
        "Теплообменники Т-17…Т-27",
        metadata={"aggregated": True, "provisional": True},
    ),
    EquipmentSpec(
        "K-1",
        "column",
        "Колонна К-1",
        tags=(
            TagSpec("k1_feed_flow_ratio", "ratio", normal_min=0.95, warning_min=0.91, critical_min=0.89),
            TagSpec("k1_pressure_bar", "bar", normal_min=1.4, normal_max=1.8),
            TagSpec("k1_top_temp_c", "degC", normal_min=130.0, normal_max=145.0),
            # Температура низа К-1 до 280 °C (сценарий, §29).
            TagSpec("k1_bottom_temp_c", "degC", normal_max=270.0, critical_max=280.0),
            TagSpec("k1_level_pct", "%", normal_min=40.0, normal_max=60.0),
        ),
    ),
    EquipmentSpec(
        "FURNACES",
        "unit_section",
        "Печи П-1…П-3",
        tags=(
            TagSpec("furnace_feed_flow_ratio", "ratio", normal_min=0.95, critical_min=0.89),
            TagSpec("furnace_outlet_temp_c", "degC", normal_min=330.0, normal_max=350.0),
            TagSpec("furnace_heat_load_pct", "%", normal_min=0.0, normal_max=105.0),
            TagSpec(
                "furnace_heat_to_feed_ratio", "ratio", normal_max=1.05, warning_max=1.15, critical_max=1.25
            ),
        ),
    ),
    EquipmentSpec("P-1", "furnace", "Печь П-1", parent_code="FURNACES"),
    EquipmentSpec("P-2", "furnace", "Печь П-2", parent_code="FURNACES"),
    EquipmentSpec("P-3", "furnace", "Печь П-3", parent_code="FURNACES"),
    EquipmentSpec(
        "K-2",
        "column",
        "Колонна К-2",
        tags=(
            # Давление верха 0,2–1 кгс/см², верх до 148 °C, низ до 350 °C (сценарий, §31).
            TagSpec("k2_pressure_bar", "bar", normal_min=0.2, normal_max=1.0),
            TagSpec("k2_top_temp_c", "degC", normal_max=142.0, critical_max=148.0),
            TagSpec("k2_bottom_temp_c", "degC", normal_max=342.0, critical_max=350.0),
            TagSpec("k2_stability_index", "ratio", normal_min=0.85, warning_min=0.70, critical_min=0.55),
        ),
    ),
    EquipmentSpec("CO-1", "circulating_reflux", "ЦО-1", parent_code="K-2"),
    EquipmentSpec("CO-2", "circulating_reflux", "ЦО-2", parent_code="K-2"),
    EquipmentSpec("CO-3", "circulating_reflux", "ЦО-3", parent_code="K-2"),
    EquipmentSpec("K-3/1", "stripping_column", "К-3/1", metadata={"fraction": "140-240"}),
    EquipmentSpec("K-3/2", "stripping_column", "К-3/2", metadata={"fraction": "240-300"}),
    EquipmentSpec("K-3/3", "stripping_column", "К-3/3", metadata={"fraction": "300-350"}),
    EquipmentSpec("K-4", "column", "Колонна К-4", metadata={"modeled": False}),
    EquipmentSpec("K-9", "column", "Колонна К-9", metadata={"modeled": False}),
    EquipmentSpec("K-10", "column", "Колонна К-10", metadata={"modeled": False}),
    EquipmentSpec(
        "PRODUCTS",
        "unit_section",
        "Продуктовые линии",
        tags=(
            TagSpec("side_draw_stability_index", "ratio", normal_min=0.85, critical_min=0.55),
            TagSpec("product_flow_stability_index", "ratio", normal_min=0.85, critical_min=0.55),
        ),
    ),
]


def feed_edges() -> list[EdgeSpec]:
    edges = [
        EdgeSpec("TANK-FARM", "N-1", "crude_suction", "crude_feed"),
        EdgeSpec("TANK-FARM", "N-1A", "crude_suction", "crude_feed"),
    ]
    for branch_no, controller in BRANCH_CONTROLLERS.items():
        chain = BRANCH_CHAINS[branch_no]
        edges.append(EdgeSpec("N-1", controller, f"branch_{branch_no}", "crude_feed", branch_no))
        edges.append(EdgeSpec(controller, chain[0], f"branch_{branch_no}", "crude_feed", branch_no))
        for upstream, downstream in pairwise(chain):
            edges.append(EdgeSpec(upstream, downstream, f"branch_{branch_no}", "crude_feed", branch_no))
        edges.append(EdgeSpec(chain[-1], "A-19", f"branch_{branch_no}", "crude_feed", branch_no))
    return edges


MAIN_LINE_EDGES = [
    EdgeSpec("A-19", "ELOU", "elou_feed", "crude_feed"),
    EdgeSpec("ELOU", "V-15", "desalted_crude", "crude_feed"),
    EdgeSpec("V-15", "N-20", "desalted_crude", "crude_feed"),
    EdgeSpec("N-20", "T-17_T-27", "desalted_crude", "crude_feed"),
    EdgeSpec("T-17_T-27", "K-1", "k1_feed", "crude_feed"),
    EdgeSpec("K-1", "FURNACES", "stripped_crude", "crude_feed"),
    EdgeSpec("FURNACES", "K-2", "furnace_outlet", "crude_feed"),
    EdgeSpec("K-2", "K-3/1", "side_draw_140_240", "product"),
    EdgeSpec("K-2", "K-3/2", "side_draw_240_300", "product"),
    EdgeSpec("K-2", "K-3/3", "side_draw_300_350", "product"),
    EdgeSpec("K-2", "K-4", "unstable_gasoline", "product"),
    EdgeSpec("K-4", "K-9", "stable_gasoline", "product"),
    EdgeSpec("K-9", "K-10", "gasoline_fraction", "product"),
    EdgeSpec("K-3/1", "PRODUCTS", "product_140_240", "product"),
    EdgeSpec("K-3/2", "PRODUCTS", "product_240_300", "product"),
    EdgeSpec("K-3/3", "PRODUCTS", "product_300_350", "product"),
    EdgeSpec("K-2", "PRODUCTS", "fuel_oil", "product"),
    EdgeSpec("A-19", "ELOU", "wash_water", "water"),
]

# Возврат тепла в сырьё. Явно названы сценарием: ЦО-1 → Т-3 (§12) и К-3/3 → Т-7/1 (§16).
# Остальные привязки горячих потоков сценарием не определены и помечены как provisional.
HOT_STREAM_EDGES = [
    EdgeSpec("CO-1", "T-3/1", "co1_hot", "hot_stream", 1),
    EdgeSpec("K-3/3", "T-7/1", "fraction_300_350_hot", "hot_stream", 2),
    EdgeSpec("CO-2", "T-4/1", "co2_hot", "hot_stream", 2, {"provisional": True}),
    EdgeSpec("CO-3", "T-9/1", "co3_hot", "hot_stream", 3, {"provisional": True}),
    EdgeSpec("K-2", "T-10/1", "fuel_oil_hot", "hot_stream", 3, {"provisional": True}),
]


def build_installation_spec() -> InstallationSpec:
    equipment = [
        *FEED_EQUIPMENT,
        *(
            EquipmentSpec(code, "flow_controller", code, tags=branch_controller_tags(branch_no))
            for branch_no, code in BRANCH_CONTROLLERS.items()
        ),
        *heat_exchanger_equipment(),
        *ELOU_EQUIPMENT,
        *ATMOSPHERIC_EQUIPMENT,
    ]
    return InstallationSpec(
        code=INSTALLATION_CODE,
        version=INSTALLATION_VERSION,
        name="Установка ЭЛОУ-АВТ",
        config={
            "provisional": True,
            "nominal_branch_flow_tph": NOMINAL_BRANCH_FLOW_TPH,
            "branch_count": len(BRANCH_CONTROLLERS),
            "t11_temperature_limit_c": T11_TEMPERATURE_LIMIT_C,
            "elou_low_level_interlock_mm": ELOU_LOW_LEVEL_INTERLOCK_MM,
        },
        equipment=tuple(equipment),
        edges=tuple([*feed_edges(), *MAIN_LINE_EDGES, *HOT_STREAM_EDGES]),
    )
