import argparse
import os
from typing import Final, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Inverter/String Configuration ---
# Inverters have 4 strings (A-D), Powerwalls have 6 strings (A-F).
# Each --inverter or --powerwall flag adds one device with an optional suffix.
# If only one device total, no suffix is needed (fields are unadorned).
# e.g. A_Power, B_Power (no suffix) vs A1_Power, B1_Power (suffix "1")
#      vs A_1JG_Power (suffix "_1JG").


def build_device_configs(inverters, powerwalls):
    """Build the device config list from --inverter and --powerwall args.

    Each entry is a dict with 'letters' and 'suffix'.
    """
    configs = []
    for suffix in inverters:
        configs.append({"letters": "ABCD", "suffix": suffix})
    for suffix in powerwalls:
        configs.append({"letters": "ABCDEF", "suffix": suffix})
    return configs


def collapse(sql):
    """Collapse multi-line SQL to a single line with normalized whitespace."""
    return ' '.join(sql.split())


def pw_fields(template, start, end):
    """Generate PW-numbered field names. e.g. pw_fields('PW{}_temp', 1, 6)."""
    return [template.format(i) for i in range(start, end + 1)]


def mean_cq(name, fields, into_policy, group_time="1m"):
    """Build a collapsed mean() continuous query for the given fields."""
    select = ", ".join(f"mean({f}) AS {f}" for f in fields)
    from_list = ", ".join(fields)
    return collapse(
        f"CREATE CONTINUOUS QUERY {name} ON powerwall "
        f"BEGIN SELECT {select} "
        f"INTO powerwall.{into_policy}.:MEASUREMENT "
        f"FROM ( SELECT {from_list} FROM raw.http ) "
        f"GROUP BY time({group_time}), month, year fill(linear) END"
    )


# --- Statement Generators ---

def generate_retention_policies():
    policies = [
        "CREATE RETENTION POLICY raw ON powerwall duration 3d replication 1",
        "ALTER RETENTION POLICY autogen ON powerwall duration 0s",
    ]
    for name, duration in [
        ('strings', '0s'), ('pwtemps', '0s'), ('vitals', '0s'),
        ('kwh', 'INF'), ('daily', 'INF'), ('monthly', 'INF'),
        ('grid', 'INF'), ('pod', 'INF'), ('alerts', 'INF'),
        ('fans', '0s'),
    ]:
        policies.append(
            f"CREATE RETENTION POLICY {name} ON powerwall duration {duration} replication 1"
        )
    return policies


def generate_fixed_cqs():
    """CQs that don't vary with inverter count."""
    return [
        collapse("""
            CREATE CONTINUOUS QUERY cq_kwh ON powerwall RESAMPLE EVERY 1m
            BEGIN SELECT integral(home)/1000/3600 AS home,
                integral(solar)/1000/3600 AS solar,
                integral(from_pw)/1000/3600 AS from_pw,
                integral(to_pw)/1000/3600 AS to_pw,
                integral(from_grid)/1000/3600 AS from_grid,
                integral(to_grid)/1000/3600 AS to_grid
                INTO powerwall.kwh.:MEASUREMENT FROM autogen.http
                GROUP BY time(1h), month, year tz('America/New_York') END
        """),
        collapse("""
            CREATE CONTINUOUS QUERY cq_grid ON powerwall
            BEGIN SELECT min(grid_status) AS grid_status
                INTO powerwall.grid.:MEASUREMENT
                FROM ( SELECT grid_status FROM raw.http )
                GROUP BY time(1m), month, year fill(linear) END
        """),
        collapse("""
            CREATE CONTINUOUS QUERY cq_alerts ON powerwall RESAMPLE FOR 2m
            BEGIN SELECT max(*)
                INTO powerwall.alerts.:MEASUREMENT
                FROM ( SELECT * FROM raw.alerts )
                GROUP BY time(1m), month, year END
        """),
        collapse("""
            CREATE CONTINUOUS QUERY cq_daily ON powerwall RESAMPLE EVERY 1h
            BEGIN SELECT sum(home) AS home, sum(solar) AS solar,
                sum(from_pw) AS from_pw, sum(to_pw) AS to_pw,
                sum(from_grid) AS from_grid, sum(to_grid) AS to_grid
                INTO powerwall.daily.:MEASUREMENT FROM powerwall.kwh.http
                GROUP BY time(1d), month, year tz('America/New_York') END
        """),
        collapse("""
            CREATE CONTINUOUS QUERY cq_monthly ON powerwall RESAMPLE EVERY 1h
            BEGIN SELECT sum(home) AS home, sum(solar) AS solar,
                sum(from_pw) AS from_pw, sum(to_pw) AS to_pw,
                sum(from_grid) AS from_grid, sum(to_grid) AS to_grid
                INTO powerwall.monthly.:MEASUREMENT FROM powerwall.daily.http
                GROUP BY time(365d), month, year END
        """),
    ]


def generate_autogen_cqs():
    return [
        collapse("""
            CREATE CONTINUOUS QUERY cq_autogen ON powerwall
            BEGIN SELECT mean(home) AS home, mean(solar) AS solar,
                mean(from_pw) AS from_pw, mean(to_pw) AS to_pw,
                mean(from_grid) AS from_grid, mean(to_grid) AS to_grid,
                last(percentage) AS percentage
                INTO powerwall.autogen.:MEASUREMENT
                FROM (
                    SELECT load_instant_power AS home,
                        solar_instant_power AS solar,
                        abs((1+battery_instant_power/abs(battery_instant_power))*battery_instant_power/2) AS from_pw,
                        abs((1-battery_instant_power/abs(battery_instant_power))*battery_instant_power/2) AS to_pw,
                        abs((1+site_instant_power/abs(site_instant_power))*site_instant_power/2) AS from_grid,
                        abs((1-site_instant_power/abs(site_instant_power))*site_instant_power/2) AS to_grid,
                        percentage FROM raw.http
                )
                GROUP BY time(1m), month, year fill(linear) END
        """),
        collapse("""
            CREATE CONTINUOUS QUERY cq_autogen_current ON powerwall
            BEGIN SELECT mean(home) AS home_current, mean(solar) AS solar_current,
                mean(pw) AS pw_current, mean(grid) AS grid_current
                INTO powerwall.autogen.:MEASUREMENT
                FROM (
                    SELECT load_instant_total_current AS home,
                        solar_instant_total_current AS solar,
                        battery_instant_total_current AS pw,
                        site_instant_total_current AS grid FROM raw.http
                )
                GROUP BY time(1m), month, year fill(linear) END
        """),
        collapse("""
            CREATE CONTINUOUS QUERY cq_autogen_voltage ON powerwall
            BEGIN SELECT mean(home) AS home_voltage, mean(solar) AS solar_voltage,
                mean(pw) AS pw_voltage, mean(grid) AS grid_voltage
                INTO powerwall.autogen.:MEASUREMENT
                FROM (
                    SELECT load_instant_average_voltage AS home,
                        solar_instant_average_voltage AS solar,
                        battery_instant_average_voltage AS pw,
                        site_instant_average_voltage AS grid FROM raw.http
                )
                GROUP BY time(1m), month, year fill(linear) END
        """),
    ]


def generate_temperature_cqs():
    return [
        mean_cq("cq_pw_temps", pw_fields("PW{}_temp", 1, 6), "pwtemps"),
        mean_cq("cq_pw_tempsb", pw_fields("PW{}_temp", 7, 12), "pwtemps"),
    ]


def generate_string_cqs(device_configs):
    METRICS: Final[List[str]] = ["_Current", "_Power", "_Voltage"]
    cqs = []
    for i, config in enumerate(device_configs):
        fields = [
            f"{letter}{config['suffix']}{metric}"
            for letter in config["letters"]
            for metric in METRICS
        ]
        cqs.append(mean_cq(f"cq_strings{i}", fields, "strings"))
    return cqs


def generate_inverter_cqs(device_configs):
    cqs = []
    for i, config in enumerate(device_configs):
        inv = f"Inverter{i}"
        power_sum = "+".join(f"{letter}{config['suffix']}_Power" for letter in config["letters"])
        cqs.append(collapse(
            f"CREATE CONTINUOUS QUERY cq_inverters{i} ON powerwall "
            f"BEGIN SELECT mean({inv}) AS {inv} "
            f"INTO powerwall.strings.:MEASUREMENT "
            f"FROM (SELECT {power_sum} AS {inv} FROM raw.http) "
            f"GROUP BY time(1m), month, year fill(linear) END"
        ))
    return cqs


def generate_vitals_cqs():
    return [
        mean_cq("cq_vitals1", pw_fields("PW{}_PINV_Fout", 1, 6), "vitals"),
        mean_cq("cq_vitals1b", pw_fields("PW{}_PINV_Fout", 7, 12), "vitals"),
        mean_cq("cq_vitals2", [
            "ISLAND_FreqL1_Load", "ISLAND_FreqL2_Load", "ISLAND_FreqL3_Load",
            "ISLAND_FreqL1_Main", "ISLAND_FreqL2_Main", "ISLAND_FreqL3_Main",
        ], "vitals"),
        mean_cq("cq_vitals3", [
            "ISLAND_VL1N_Load", "ISLAND_VL2N_Load", "ISLAND_VL3N_Load",
            "METER_X_VL1N", "METER_X_VL2N", "METER_X_VL3N",
        ], "vitals"),
        mean_cq("cq_vitals4", pw_fields("PW{}_PINV_VSplit1", 1, 6), "vitals"),
        mean_cq("cq_vitals4b", pw_fields("PW{}_PINV_VSplit1", 7, 12), "vitals"),
        mean_cq("cq_vitals5", pw_fields("PW{}_PINV_VSplit2", 1, 6), "vitals"),
        mean_cq("cq_vitals5b", pw_fields("PW{}_PINV_VSplit2", 7, 12), "vitals"),
        mean_cq("cq_vitals6", [
            "METER_Z_VL1G", "METER_Z_VL2G", "METER_Z_CTA_I", "METER_Z_CTB_I",
        ], "vitals"),
        mean_cq("cq_vitals7", [
            "ISLAND_VL1N_Main", "ISLAND_VL2N_Main", "ISLAND_VL3N_Main",
        ], "vitals", group_time="15s"),
        mean_cq("cq_vitals8", pw_fields("PW{}_v_out", 1, 12), "vitals"),
        mean_cq("cq_vitals9", pw_fields("PW{}_f_out", 1, 12), "vitals"),
        mean_cq("cq_vitals10", pw_fields("PW{}_i_out", 1, 12), "vitals"),
        mean_cq("cq_vitals11", pw_fields("PW{}_p_out", 1, 12), "vitals"),
        mean_cq("cq_vitals12", pw_fields("PW{}_q_out", 1, 12), "vitals"),
    ]


def generate_fan_cqs():
    fan_fields = (
        [f"FAN{i}_target" for i in range(1, 7)]
        + [f"FAN{i}_actual" for i in range(1, 7)]
    )
    return [mean_cq("cq_fans", fan_fields, "fans")]


def generate_pod_cqs():
    return [
        mean_cq("cq_pod1", pw_fields("PW{}_POD_nom_energy_remaining", 1, 6), "pod"),
        mean_cq("cq_pod1b", pw_fields("PW{}_POD_nom_energy_remaining", 7, 12), "pod"),
        mean_cq("cq_pod2", pw_fields("PW{}_POD_nom_full_pack_energy", 1, 6), "pod"),
        mean_cq("cq_pod2b", pw_fields("PW{}_POD_nom_full_pack_energy", 7, 12), "pod"),
        mean_cq("cq_pod3", ["backup_reserve_percent"], "pod"),
        mean_cq("cq_pod4", ["nominal_full_pack_energy", "nominal_energy_remaining"], "pod"),
    ]


def extract_cq_names(statements):
    """Extract CQ names from CREATE CONTINUOUS QUERY statements."""
    names = []
    for s in statements:
        if s.startswith("CREATE CONTINUOUS QUERY"):
            names.append(s.split()[3])
    return names


def main():
    parser = argparse.ArgumentParser(
        description="Generate InfluxDB continuous queries for Powerwall Dashboard.",
        epilog="Examples:\n"
               "  %(prog)s --inverter                          # single inverter, unadorned\n"
               "  %(prog)s --inverter --inverter 1              # two inverters\n"
               "  %(prog)s --inverter --inverter 1 --inverter _1JG --inverter _KW7\n"
               "  %(prog)s --powerwall                          # single powerwall, unadorned\n"
               "  %(prog)s --inverter --powerwall 1             # one inverter + one powerwall\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--inverter', nargs='?', const='', action='append',
        default=[], metavar='SUFFIX',
        help='Add an inverter (4 strings ABCD). Optional SUFFIX for field names.'
    )
    parser.add_argument(
        '--powerwall', nargs='?', const='', action='append',
        default=[], metavar='SUFFIX',
        help='Add a powerwall (6 strings ABCDEF). Optional SUFFIX for field names.'
    )
    args = parser.parse_args()

    if not args.inverter and not args.powerwall:
        parser.error("At least one --inverter or --powerwall is required.")

    all_suffixes = args.inverter + args.powerwall
    dupes = [s for s in set(all_suffixes) if all_suffixes.count(s) > 1]
    if dupes:
        labels = [repr(s) if s else '(unadorned)' for s in dupes]
        parser.error(f"Duplicate suffixes: {', '.join(labels)}")

    device_configs = build_device_configs(args.inverter, args.powerwall)
    num_devices = len(device_configs)

    retention = generate_retention_policies()

    cqs = []
    cqs.extend(generate_fixed_cqs())
    cqs.extend(generate_autogen_cqs())
    cqs.extend(generate_temperature_cqs())
    cqs.extend(generate_string_cqs(device_configs))
    cqs.extend(generate_inverter_cqs(device_configs))
    cqs.extend(generate_vitals_cqs())
    cqs.extend(generate_pod_cqs())
    cqs.extend(generate_fan_cqs())

    all_statements = retention + cqs

    # Write influxdb.sql (for influx -import)
    collapsed_path = os.path.join(SCRIPT_DIR, 'influxdb.sql')
    with open(collapsed_path, 'w') as f:
        f.write("# DDL\n")
        for s in all_statements:
            f.write(s + "\n")

    # Write dropcq.sql (for dropping all CQs before re-import)
    cq_names = extract_cq_names(cqs)
    dropcq_path = os.path.join(SCRIPT_DIR, 'dropcq.sql')
    with open(dropcq_path, 'w') as f:
        f.write("# DDL\n")
        for name in cq_names:
            f.write(f"DROP CONTINUOUS QUERY {name} ON powerwall\n")

    print(f"Generated {collapsed_path} ({len(all_statements)} statements, "
          f"{num_devices} devices)")
    print(f"Generated {dropcq_path} ({len(cq_names)} CQ drop statements)")


if __name__ == "__main__":
    main()
