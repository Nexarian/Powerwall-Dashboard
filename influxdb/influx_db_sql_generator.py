from typing import Final, List
from jinja2 import Environment, FileSystemLoader
import os

# Create a Jinja2 environment
env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))

# Define the template
template_string = """
# DDL
# USE powerwall
CREATE DATABASE powerwall

# Retention Queries
CREATE RETENTION POLICY raw ON powerwall duration 3d replication 1
ALTER RETENTION POLICY autogen ON powerwall duration 0s
{% for policy in retention_policies %}
CREATE RETENTION POLICY {{ policy.name }} ON powerwall duration {{ policy.duration }} replication 1
{% endfor %}

CREATE CONTINUOUS QUERY cq_kwh ON powerwall RESAMPLE EVERY 1m
BEGIN 
    SELECT integral(home)/1000/3600 AS home,
           integral(solar)/1000/3600 AS solar,
           integral(from_pw)/1000/3600 AS from_pw,
           integral(to_pw)/1000/3600 AS to_pw,
           integral(from_grid)/1000/3600 AS from_grid,
           integral(to_grid)/1000/3600 AS to_grid
    INTO powerwall.kwh.:MEASUREMENT
    FROM autogen.http
    GROUP BY time(1h), month, year tz('America/New_York')
END


CREATE CONTINUOUS QUERY cq_grid ON powerwall
BEGIN
    SELECT min(grid_status) AS grid_status 
    INTO powerwall.grid.:MEASUREMENT 
    FROM (
        SELECT grid_status FROM raw.http
    ) GROUP BY time(1m), month, year fill(linear)
END


CREATE CONTINUOUS QUERY cq_alerts ON powerwall RESAMPLE FOR 2m
BEGIN
    SELECT max(*)
    INTO powerwall.alerts.:MEASUREMENT
    FROM (
        SELECT * FROM raw.alerts
    ) GROUP BY time(1m), month, year
END


# Temporal Frequency Queries
{% for query in temporal_frequency_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON {{ query.database }}
RESAMPLE EVERY {{ query.resample_every }}
BEGIN
    SELECT {{ query.select_clause }}
    INTO {{ query.into_clause }}
    FROM {{ query.from_clause }}
    GROUP BY {{ query.group_by_clause }}
END
{% endfor %}

# Autogen queries
{% for query in autogen_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON {{ query.database }}
BEGIN
    SELECT {{ query.select_clause }}
    INTO {{ query.into_clause }}
    FROM {{ query.from_clause }}
    GROUP BY {{ query.group_by_clause }}
END
{% endfor %}

# Temperature queries
{% for query in temperature_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON {{ query.database }}
BEGIN
    SELECT {{ query.select_clause }}
    INTO {{ query.into_clause }}
    FROM {{ query.from_clause }}
    GROUP BY {{ query.group_by_clause }}
END
{% endfor %}

{% for query in string_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON powerwall
BEGIN
    SELECT
    {%- for field in query.fields %}
        mean({{ field }}) AS {{ field }}{% if not loop.last %}, {% endif %}
    {%- endfor %}
    INTO powerwall.strings.:MEASUREMENT
    FROM (SELECT {{ query.fields|join(', ') }} FROM raw.http)
    GROUP BY time(1m), month, year fill(linear)
END
{% endfor %}

{% for query in inverter_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON {{ query.database }}
BEGIN
    SELECT {{ query.select_clause }}
    INTO {{ query.into_clause }}
    FROM {{ query.from_clause }}
    GROUP BY {{ query.group_by_clause }}
END
{% endfor %}

{% for query in vital_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON {{ query.database }}
BEGIN
    SELECT {{ query.select_clause }}
    INTO {{ query.into_clause }}
    FROM {{ query.from_clause }}
    GROUP BY {{ query.group_by_clause }}
END
{% endfor %}

{% for query in pod_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON {{ query.database }}
BEGIN
    SELECT {{ query.select_clause }}
    INTO {{ query.into_clause }}
    FROM {{ query.from_clause }}
    GROUP BY {{ query.group_by_clause }}
END
{% endfor %}


{% for query in continuous_queries %}
CREATE CONTINUOUS QUERY {{ query.name }} ON powerwall {{ query.resample }}BEGIN {{ query.select }} INTO {{ query.into }} FROM ({{ query.from }}) GROUP BY {{ query.group_by }} {{ query.fill }} END
{% endfor %}
"""

# Create the template
template = env.from_string(template_string)

# Define the data

retention_policies = [
    {'name': 'strings', 'duration': '0s'},
    {'name': 'pwtemps', 'duration': '0s'},
    {'name': 'vitals', 'duration': '0s'},
    {'name': 'kwh', 'duration': 'INF'},
    {'name': 'daily', 'duration': 'INF'},
    {'name': 'monthly', 'duration': 'INF'},
    {'name': 'grid', 'duration': 'INF'},
    {'name': 'pod', 'duration': 'INF'},
    {'name': 'alerts', 'duration': 'INF'}
]

temporal_frequency_queries = [
    {
        "name": "cq_daily",
        "database": "powerwall",
        "resample_every": "1h",
        "select_clause": """sum(home) AS home,
            sum(solar) AS solar,
            sum(from_pw) AS from_pw,
            sum(to_pw) AS to_pw,
            sum(from_grid) AS from_grid,
            sum(to_grid) AS to_grid""",
        "into_clause": "powerwall.daily.:MEASUREMENT",
        "from_clause": "powerwall.kwh.http",
        "group_by_clause": "time(1d), month, year tz('America/New_York')"
    },
    {
        "name": "cq_monthly",
        "database": "powerwall",
        "resample_every": "1h",
        "select_clause": """sum(home) AS home,
            sum(solar) AS solar,
            sum(from_pw) AS from_pw,
            sum(to_pw) AS to_pw,
            sum(from_grid) AS from_grid,
            sum(to_grid) AS to_grid""",
        "into_clause": "powerwall.monthly.:MEASUREMENT",
        "from_clause": "powerwall.daily.http",
        "group_by_clause": "time(365d), month, year"
    }
]

autogen_queries = queries = [
    {
        "name": "cq_autogen",
        "database": "powerwall",
        "select_clause": """mean(home) AS home,
            mean(solar) AS solar,
            mean(from_pw) AS from_pw,
            mean(to_pw) AS to_pw,
            mean(from_grid) AS from_grid,
            mean(to_grid) AS to_grid,
            last(percentage) AS percentage""",
            "into_clause": "powerwall.autogen.:MEASUREMENT",
            "from_clause": """(
                SELECT load_instant_power AS home,
                    solar_instant_power AS solar,
                    abs((1+battery_instant_power/abs(battery_instant_power))*battery_instant_power/2) AS from_pw,
                    abs((1-battery_instant_power/abs(battery_instant_power))*battery_instant_power/2) AS to_pw,
                    abs((1+site_instant_power/abs(site_instant_power))*site_instant_power/2) AS from_grid,
                    abs((1-site_instant_power/abs(site_instant_power))*site_instant_power/2) AS to_grid,
                    percentage
                FROM raw.http
            )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_autogen_current",
        "database": "powerwall",
        "select_clause": """mean(home) AS home_current,
            mean(solar) AS solar_current,
            mean(pw)   AS pw_current,
            mean(grid) AS grid_current""",
            "into_clause": "powerwall.autogen.:MEASUREMENT",
            "from_clause": """(
                SELECT load_instant_total_current AS home,
                    solar_instant_total_current AS solar,
                    battery_instant_total_current AS pw,
                    site_instant_total_current AS grid
                FROM raw.http
            )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_autogen_voltage",
        "database": "powerwall",
        "select_clause": """mean(home) AS home_voltage,
            mean(solar) AS solar_voltage,
            mean(pw)   AS pw_voltage,
            mean(grid) AS grid_voltage""",
            "into_clause": "powerwall.autogen.:MEASUREMENT",
            "from_clause": """(
                SELECT load_instant_average_voltage AS home,
                    solar_instant_average_voltage AS solar,
                    battery_instant_average_voltage AS pw,
                    site_instant_average_voltage AS grid
                FROM raw.http
            )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    }
]

temperature_queries = [
    {
        "name": "cq_pw_temps",
        "database": "powerwall",
        "select_clause": """mean(PW1_temp) AS PW1_temp,
            mean(PW2_temp) AS PW2_temp,
            mean(PW3_temp) AS PW3_temp,
            mean(PW4_temp) AS PW4_temp,
            mean(PW5_temp) AS PW5_temp,
            mean(PW6_temp) AS PW6_temp""",
        "into_clause": "powerwall.pwtemps.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_temp, PW2_temp, PW3_temp, PW4_temp, PW5_temp, PW6_temp
                FROM raw.http
            )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_pw_tempsb",
        "database": "powerwall",
        "select_clause": """mean(PW7_temp) AS PW7_temp,
            mean(PW8_temp) AS PW8_temp,
            mean(PW9_temp) AS PW9_temp,
            mean(PW10_temp) AS PW10_temp,
            mean(PW11_temp) AS PW11_temp,
            mean(PW12_temp) AS PW12_temp""",
        "into_clause": "powerwall.pwtemps.:MEASUREMENT",
        "from_clause": """(
            SELECT PW7_temp, PW8_temp, PW9_temp, PW10_temp, PW11_temp, PW12_temp
                FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    }
]


def generate_string_queries():
    # Each entry describes:
    #   1) the range of i-values to which it applies
    #   2) the letters to use (e.g. ABCD or EF)
    #   3) a function for computing suffix (could be "", a number, etc.)
    #   4) which metrics to append
    
    METRICS: Final[List[str]] = ["_Current", "_Power", "_Voltage"]

    configs = [
        {
            "range": range(0, 6),
            "letters": "ABCD",
            "suffix_func": lambda i: "" if i == 0 else str(i)
        },
        {
            "range": range(6, 11),
            "letters": "EF",
            "suffix_func": lambda i: str(i - 5)  # i=6 => '1', ..., i=10 => '5'
        },
        {
            "range": range(11, 12),
            "letters": "EF",
            "suffix_func": lambda i: ""
        },
        {
            "range": range(12, 13),
            "letters": "ABCD",
            "suffix_func": lambda i: "_1JG"
        },
        {
            "range": range(13, 14),
            "letters": "ABCD",
            "suffix_func": lambda i: "_2N1"
        }
    ]

    queries = []
    for i in range(14):  # We have 0..13 inclusive
        # 1) find which config applies to i
        config = next(c for c in configs if i in c["range"])

        # 2) extract letters, suffix, and metrics
        letters = config["letters"]
        suffix = config["suffix_func"](i)
        metrics = METRICS

        # 3) build the fields
        fields = [
            f"{letter}{suffix}{metric}"
            for letter in letters
            for metric in metrics
        ]

        # 4) build the query name, e.g. "cq_strings" for i=0 or "cq_strings1" for i=1
        name_suffix = "" if i == 0 else str(i)
        name = f"cq_strings{name_suffix}"

        # 5) assemble the final dictionary
        queries.append({"name": name, "fields": fields})

    return queries
string_queries = generate_string_queries()


inverter_queries = [
    {
        "name": "cq_inverters",
        "database": "powerwall",
        "select_clause": """mean(Inverter1) AS Inverter1,
            mean(Inverter2) AS Inverter2,
            mean(Inverter3) AS Inverter3,
            mean(Inverter4) AS Inverter4""",
        "into_clause": "powerwall.strings.:MEASUREMENT",
        "from_clause": """(
            SELECT A_Power+B_Power+C_Power+D_Power+E_Power+F_Power      AS Inverter1,
                A1_Power+B1_Power+C1_Power+D1_Power+E1_Power+F1_Power   AS Inverter2,
                A2_Power+B2_Power+C2_Power+D2_Power+E2_Power+F2_Power   AS Inverter3,
                A3_Power+B3_Power+C3_Power+D3_Power+E3_Power+F3_Power   AS Inverter4
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_inverters1",
        "database": "powerwall",
        "select_clause": """mean(Inverter5) AS Inverter5,
            mean(Inverter6) AS Inverter6""",
        "into_clause": "powerwall.strings.:MEASUREMENT",
        "from_clause": """(
            SELECT A4_Power+B4_Power+C4_Power+D4_Power+E4_Power+F4_Power   AS Inverter5,
                A5_Power+B5_Power+C5_Power+D5_Power+E5_Power+F5_Power   AS Inverter6
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    }
]

vital_queries = queries = [
    {
        "name": "cq_vitals1",
        "database": "powerwall",
        "select_clause": """mean(PW1_PINV_Fout) AS PW1_PINV_Fout,
            mean(PW2_PINV_Fout) AS PW2_PINV_Fout,
            mean(PW3_PINV_Fout) AS PW3_PINV_Fout,
            mean(PW4_PINV_Fout) AS PW4_PINV_Fout,
            mean(PW5_PINV_Fout) AS PW5_PINV_Fout,
            mean(PW6_PINV_Fout) AS PW6_PINV_Fout""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_PINV_Fout, PW2_PINV_Fout, PW3_PINV_Fout, PW4_PINV_Fout, PW5_PINV_Fout, PW6_PINV_Fout
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals1b",
        "database": "powerwall",
        "select_clause": """mean(PW7_PINV_Fout) AS PW7_PINV_Fout,
            mean(PW8_PINV_Fout) AS PW8_PINV_Fout,
            mean(PW9_PINV_Fout) AS PW9_PINV_Fout,
            mean(PW10_PINV_Fout) AS PW10_PINV_Fout,
            mean(PW11_PINV_Fout) AS PW11_PINV_Fout,
            mean(PW12_PINV_Fout) AS PW12_PINV_Fout""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW7_PINV_Fout, PW8_PINV_Fout, PW9_PINV_Fout, PW10_PINV_Fout, PW11_PINV_Fout, PW12_PINV_Fout
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals2",
        "database": "powerwall",
        "select_clause": """mean(ISLAND_FreqL1_Load) AS ISLAND_FreqL1_Load,
            mean(ISLAND_FreqL2_Load) AS ISLAND_FreqL2_Load,
            mean(ISLAND_FreqL3_Load) AS ISLAND_FreqL3_Load,
            mean(ISLAND_FreqL1_Main) AS ISLAND_FreqL1_Main,
            mean(ISLAND_FreqL2_Main) AS ISLAND_FreqL2_Main,
            mean(ISLAND_FreqL3_Main) AS ISLAND_FreqL3_Main""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT ISLAND_FreqL1_Load, ISLAND_FreqL2_Load, ISLAND_FreqL3_Load,
                ISLAND_FreqL1_Main, ISLAND_FreqL2_Main, ISLAND_FreqL3_Main
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals3",
        "database": "powerwall",
        "select_clause": """mean(ISLAND_VL1N_Load) AS ISLAND_VL1N_Load,
            mean(ISLAND_VL2N_Load) AS ISLAND_VL2N_Load,
            mean(ISLAND_VL3N_Load) AS ISLAND_VL3N_Load,
            mean(METER_X_VL1N) AS METER_X_VL1N,
            mean(METER_X_VL2N) AS METER_X_VL2N,
            mean(METER_X_VL3N) AS METER_X_VL3N""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT ISLAND_VL1N_Load, ISLAND_VL2N_Load, ISLAND_VL3N_Load,
                METER_X_VL1N, METER_X_VL2N, METER_X_VL3N
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_vitals4",
        "database": "powerwall",
        "select_clause": """mean(PW1_PINV_VSplit1) AS PW1_PINV_VSplit1,
            mean(PW2_PINV_VSplit1) AS PW2_PINV_VSplit1,
            mean(PW3_PINV_VSplit1) AS PW3_PINV_VSplit1,
            mean(PW4_PINV_VSplit1) AS PW4_PINV_VSplit1,
            mean(PW5_PINV_VSplit1) AS PW5_PINV_VSplit1,
            mean(PW6_PINV_VSplit1) AS PW6_PINV_VSplit1""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_PINV_VSplit1, PW2_PINV_VSplit1, PW3_PINV_VSplit1,
                PW4_PINV_VSplit1, PW5_PINV_VSplit1, PW6_PINV_VSplit1
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_vitals4b",
        "database": "powerwall",
        "select_clause": """mean(PW7_PINV_VSplit1) AS PW7_PINV_VSplit1,
            mean(PW8_PINV_VSplit1) AS PW8_PINV_VSplit1,
            mean(PW9_PINV_VSplit1) AS PW9_PINV_VSplit1,
            mean(PW10_PINV_VSplit1) AS PW10_PINV_VSplit1,
            mean(PW11_PINV_VSplit1) AS PW11_PINV_VSplit1,
            mean(PW12_PINV_VSplit1) AS PW12_PINV_VSplit1""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW7_PINV_VSplit1, PW8_PINV_VSplit1, PW9_PINV_VSplit1,
                PW10_PINV_VSplit1, PW11_PINV_VSplit1, PW12_PINV_VSplit1
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_vitals5",
        "database": "powerwall",
        "select_clause": """mean(PW1_PINV_VSplit2) AS PW1_PINV_VSplit2,
            mean(PW2_PINV_VSplit2) AS PW2_PINV_VSplit2,
            mean(PW3_PINV_VSplit2) AS PW3_PINV_VSplit2,
            mean(PW4_PINV_VSplit2) AS PW4_PINV_VSplit2,
            mean(PW5_PINV_VSplit2) AS PW5_PINV_VSplit2,
            mean(PW6_PINV_VSplit2) AS PW6_PINV_VSplit2""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_PINV_VSplit2, PW2_PINV_VSplit2, PW3_PINV_VSplit2,
                PW4_PINV_VSplit2, PW5_PINV_VSplit2, PW6_PINV_VSplit2
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals5b",
        "database": "powerwall",
        "select_clause": """mean(PW7_PINV_VSplit2) AS PW7_PINV_VSplit2,
            mean(PW8_PINV_VSplit2) AS PW8_PINV_VSplit2,
            mean(PW9_PINV_VSplit2) AS PW9_PINV_VSplit2,
            mean(PW10_PINV_VSplit2) AS PW10_PINV_VSplit2,
            mean(PW11_PINV_VSplit2) AS PW11_PINV_VSplit2,
            mean(PW12_PINV_VSplit2) AS PW12_PINV_VSplit2""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW7_PINV_VSplit2, PW8_PINV_VSplit2, PW9_PINV_VSplit2,
                PW10_PINV_VSplit2, PW11_PINV_VSplit2, PW12_PINV_VSplit2
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals6",
        "database": "powerwall",
        "select_clause": """mean(METER_Z_VL1G) AS METER_Z_VL1G,
            mean(METER_Z_VL2G) AS METER_Z_VL2G,
            mean(METER_Z_CTA_I) AS METER_Z_CTA_I,
            mean(METER_Z_CTB_I) AS METER_Z_CTB_I""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT METER_Z_VL1G, METER_Z_VL2G, METER_Z_CTA_I, METER_Z_CTB_I
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals7",
        "database": "powerwall",
        "select_clause": """mean(ISLAND_VL1N_Main) AS ISLAND_VL1N_Main,
            mean(ISLAND_VL2N_Main) AS ISLAND_VL2N_Main,
            mean(ISLAND_VL3N_Main) AS ISLAND_VL3N_Main""",
                "into_clause": "powerwall.vitals.:MEASUREMENT",
                "from_clause": """(
            SELECT ISLAND_VL1N_Main, ISLAND_VL2N_Main, ISLAND_VL3N_Main
            FROM raw.http
        )""",
        # Notice the time(15s) instead of time(1m):
        "group_by_clause": "time(15s), month, year fill(linear)"
    },
    {
        "name": "cq_vitals8",
        "database": "powerwall",
        "select_clause": """mean(PW1_v_out) AS PW1_v_out,
            mean(PW2_v_out) AS PW2_v_out,
            mean(PW3_v_out) AS PW3_v_out,
            mean(PW4_v_out) AS PW4_v_out,
            mean(PW5_v_out) AS PW5_v_out,
            mean(PW6_v_out) AS PW6_v_out,
            mean(PW7_v_out) AS PW7_v_out,
            mean(PW8_v_out) AS PW8_v_out,
            mean(PW9_v_out) AS PW9_v_out,
            mean(PW10_v_out) AS PW10_v_out,
            mean(PW11_v_out) AS PW11_v_out,
            mean(PW12_v_out) AS PW12_v_out""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_v_out, PW2_v_out, PW3_v_out, PW4_v_out, PW5_v_out, PW6_v_out,
                PW7_v_out, PW8_v_out, PW9_v_out, PW10_v_out, PW11_v_out, PW12_v_out
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals9",
        "database": "powerwall",
        "select_clause": """mean(PW1_f_out) AS PW1_f_out,
            mean(PW2_f_out) AS PW2_f_out,
            mean(PW3_f_out) AS PW3_f_out,
            mean(PW4_f_out) AS PW4_f_out,
            mean(PW5_f_out) AS PW5_f_out,
            mean(PW6_f_out) AS PW6_f_out,
            mean(PW7_f_out) AS PW7_f_out,
            mean(PW8_f_out) AS PW8_f_out,
            mean(PW9_f_out) AS PW9_f_out,
            mean(PW10_f_out) AS PW10_f_out,
            mean(PW11_f_out) AS PW11_f_out,
            mean(PW12_f_out) AS PW12_f_out""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_f_out, PW2_f_out, PW3_f_out, PW4_f_out, PW5_f_out, PW6_f_out,
                PW7_f_out, PW8_f_out, PW9_f_out, PW10_f_out, PW11_f_out, PW12_f_out
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals10",
        "database": "powerwall",
        "select_clause": """mean(PW1_i_out) AS PW1_i_out,
            mean(PW2_i_out) AS PW2_i_out,
            mean(PW3_i_out) AS PW3_i_out,
            mean(PW4_i_out) AS PW4_i_out,
            mean(PW5_i_out) AS PW5_i_out,
            mean(PW6_i_out) AS PW6_i_out,
            mean(PW7_i_out) AS PW7_i_out,
            mean(PW8_i_out) AS PW8_i_out,
            mean(PW9_i_out) AS PW9_i_out,
            mean(PW10_i_out) AS PW10_i_out,
            mean(PW11_i_out) AS PW11_i_out,
            mean(PW12_i_out) AS PW12_i_out""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_i_out, PW2_i_out, PW3_i_out, PW4_i_out, PW5_i_out, PW6_i_out,
                PW7_i_out, PW8_i_out, PW9_i_out, PW10_i_out, PW11_i_out, PW12_i_out
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals11",
        "database": "powerwall",
        "select_clause": """mean(PW1_p_out) AS PW1_p_out,
            mean(PW2_p_out) AS PW2_p_out,
            mean(PW3_p_out) AS PW3_p_out,
            mean(PW4_p_out) AS PW4_p_out,
            mean(PW5_p_out) AS PW5_p_out,
            mean(PW6_p_out) AS PW6_p_out,
            mean(PW7_p_out) AS PW7_p_out,
            mean(PW8_p_out) AS PW8_p_out,
            mean(PW9_p_out) AS PW9_p_out,
            mean(PW10_p_out) AS PW10_p_out,
            mean(PW11_p_out) AS PW11_p_out,
            mean(PW12_p_out) AS PW12_p_out""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_p_out, PW2_p_out, PW3_p_out, PW4_p_out, PW5_p_out, PW6_p_out,
                PW7_p_out, PW8_p_out, PW9_p_out, PW10_p_out, PW11_p_out, PW12_p_out
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    },
    {
        "name": "cq_vitals12",
        "database": "powerwall",
        "select_clause": """mean(PW1_q_out) AS PW1_q_out,
            mean(PW2_q_out) AS PW2_q_out,
            mean(PW3_q_out) AS PW3_q_out,
            mean(PW4_q_out) AS PW4_q_out,
            mean(PW5_q_out) AS PW5_q_out,
            mean(PW6_q_out) AS PW6_q_out,
            mean(PW7_q_out) AS PW7_q_out,
            mean(PW8_q_out) AS PW8_q_out,
            mean(PW9_q_out) AS PW9_q_out,
            mean(PW10_q_out) AS PW10_q_out,
            mean(PW11_q_out) AS PW11_q_out,
            mean(PW12_q_out) AS PW12_q_out""",
        "into_clause": "powerwall.vitals.:MEASUREMENT",
        "from_clause": """(
            SELECT PW1_q_out, PW2_q_out, PW3_q_out, PW4_q_out, PW5_q_out, PW6_q_out,
                PW7_q_out, PW8_q_out, PW9_q_out, PW10_q_out, PW11_q_out, PW12_q_out
            FROM raw.http
        )""",
        "group_by_clause": "time(1m), month, year fill(linear)"
    }
]

pod_queries = [
    {
        "name": "cq_pod1",
        "database": "powerwall",
        "select_clause": """mean(PW1_POD_nom_energy_remaining) AS PW1_POD_nom_energy_remaining,
    mean(PW2_POD_nom_energy_remaining) AS PW2_POD_nom_energy_remaining,
    mean(PW3_POD_nom_energy_remaining) AS PW3_POD_nom_energy_remaining,
    mean(PW4_POD_nom_energy_remaining) AS PW4_POD_nom_energy_remaining,
    mean(PW5_POD_nom_energy_remaining) AS PW5_POD_nom_energy_remaining,
    mean(PW6_POD_nom_energy_remaining) AS PW6_POD_nom_energy_remaining""",
        "into_clause": "powerwall.pod.:MEASUREMENT",
        "from_clause": """(
    SELECT PW1_POD_nom_energy_remaining,
           PW2_POD_nom_energy_remaining,
           PW3_POD_nom_energy_remaining,
           PW4_POD_nom_energy_remaining,
           PW5_POD_nom_energy_remaining,
           PW6_POD_nom_energy_remaining
    FROM raw.http
)""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_pod1b",
        "database": "powerwall",
        "select_clause": """mean(PW7_POD_nom_energy_remaining) AS PW7_POD_nom_energy_remaining,
    mean(PW8_POD_nom_energy_remaining) AS PW8_POD_nom_energy_remaining,
    mean(PW9_POD_nom_energy_remaining) AS PW9_POD_nom_energy_remaining,
    mean(PW10_POD_nom_energy_remaining) AS PW10_POD_nom_energy_remaining,
    mean(PW11_POD_nom_energy_remaining) AS PW11_POD_nom_energy_remaining,
    mean(PW12_POD_nom_energy_remaining) AS PW12_POD_nom_energy_remaining""",
        "into_clause": "powerwall.pod.:MEASUREMENT",
        "from_clause": """(
    SELECT PW7_POD_nom_energy_remaining,
           PW8_POD_nom_energy_remaining,
           PW9_POD_nom_energy_remaining,
           PW10_POD_nom_energy_remaining,
           PW11_POD_nom_energy_remaining,
           PW12_POD_nom_energy_remaining
    FROM raw.http
)""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_pod2",
        "database": "powerwall",
        "select_clause": """mean(PW1_POD_nom_full_pack_energy) AS PW1_POD_nom_full_pack_energy,
    mean(PW2_POD_nom_full_pack_energy) AS PW2_POD_nom_full_pack_energy,
    mean(PW3_POD_nom_full_pack_energy) AS PW3_POD_nom_full_pack_energy,
    mean(PW4_POD_nom_full_pack_energy) AS PW4_POD_nom_full_pack_energy,
    mean(PW5_POD_nom_full_pack_energy) AS PW5_POD_nom_full_pack_energy,
    mean(PW6_POD_nom_full_pack_energy) AS PW6_POD_nom_full_pack_energy""",
        "into_clause": "powerwall.pod.:MEASUREMENT",
        "from_clause": """(
    SELECT PW1_POD_nom_full_pack_energy,
           PW2_POD_nom_full_pack_energy,
           PW3_POD_nom_full_pack_energy,
           PW4_POD_nom_full_pack_energy,
           PW5_POD_nom_full_pack_energy,
           PW6_POD_nom_full_pack_energy
    FROM raw.http
)""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_pod2b",
        "database": "powerwall",
        "select_clause": """mean(PW7_POD_nom_full_pack_energy) AS PW7_POD_nom_full_pack_energy,
    mean(PW8_POD_nom_full_pack_energy) AS PW8_POD_nom_full_pack_energy,
    mean(PW9_POD_nom_full_pack_energy) AS PW9_POD_nom_full_pack_energy,
    mean(PW10_POD_nom_full_pack_energy) AS PW10_POD_nom_full_pack_energy,
    mean(PW11_POD_nom_full_pack_energy) AS PW11_POD_nom_full_pack_energy,
    mean(PW12_POD_nom_full_pack_energy) AS PW12_POD_nom_full_pack_energy""",
        "into_clause": "powerwall.pod.:MEASUREMENT",
        "from_clause": """(
    SELECT PW7_POD_nom_full_pack_energy,
           PW8_POD_nom_full_pack_energy,
           PW9_POD_nom_full_pack_energy,
           PW10_POD_nom_full_pack_energy,
           PW11_POD_nom_full_pack_energy,
           PW12_POD_nom_full_pack_energy
    FROM raw.http
)""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_pod3",
        "database": "powerwall",
        "select_clause": "mean(backup_reserve_percent) AS backup_reserve_percent",
        "into_clause": "powerwall.pod.:MEASUREMENT",
        "from_clause": """(
    SELECT backup_reserve_percent
    FROM raw.http
)""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
    {
        "name": "cq_pod4",
        "database": "powerwall",
        "select_clause": """mean(nominal_full_pack_energy) AS nominal_full_pack_energy,
    mean(nominal_energy_remaining) AS nominal_energy_remaining""",
        "into_clause": "powerwall.pod.:MEASUREMENT",
        "from_clause": """(
    SELECT nominal_full_pack_energy,
           nominal_energy_remaining
    FROM raw.http
)""",
        "group_by_clause": "time(1m), month, year fill(linear)",
    },
]

data = {
    "retention_policies": retention_policies,
    "temporal_frequency_queries": temporal_frequency_queries,
    "autogen_queries": autogen_queries,
    "temperature_queries": temperature_queries,
    "string_queries": string_queries,
    "inverter_queries": inverter_queries,
    "vital_queries": vital_queries,
    "pod_queries": pod_queries
}


def collapse_sql_to_single_lines(input_file, output_file):
    """
    Reads multi-line continuous queries from `input_file` and writes them
    as single-line queries into `output_file`.
    """
    with open(input_file, 'r') as f:
        lines = f.read().splitlines()
    
    queries = []
    current_query_lines = []
    in_query = False

    for line in lines:
        stripped = line.strip()

        # Skip empty or comment lines (optional: remove if you want to keep comments)
        if not stripped or stripped.startswith('#'):
            continue

        # Detect start of a query (if you want to be more precise, you can test for
        # "CREATE CONTINUOUS QUERY" or similar patterns)
        upper = stripped.upper()

        if "RETENTION" in upper and not in_query:
            queries.append(upper)
            continue

        if upper.startswith("CREATE CONTINUOUS QUERY"):
            in_query = True

        if in_query:
            current_query_lines.append(stripped)

        # Detect end of a query
        if upper == "END":
            # Collapse current query into a single line
            single_line_query = " ".join(current_query_lines)
            queries.append(single_line_query)
            current_query_lines = []
            in_query = False

    # Write out single-line queries
    with open(output_file, 'w') as out:
        for query in queries:
            out.write(query + "\n")

def main() -> None:
    # Render the template
    output = template.render(data)

    # Write the output to a file
    with open('output.txt', 'w') as f:
        f.write(output)
        
    collapse_sql_to_single_lines("output.txt", "collapsed.txt")

    print("File generated successfully!")

if __name__ == "__main__":
    main()

# continuous_queries = [
#     {
#         'name': 'cq_autogen',
#         'resample': '',
#         'select': 'SELECT mean(home) AS home, mean(solar) AS solar, mean(from_pw) AS from_pw, mean(to_pw) AS to_pw, mean(from_grid) AS from_grid, mean(to_grid) AS to_grid, last(percentage) AS percentage',
#         'into': 'powerwall.autogen.:MEASUREMENT',
#         'from': 'SELECT load_instant_power AS home, solar_instant_power AS solar, abs((1+battery_instant_power/abs(battery_instant_power))*battery_instant_power/2) AS from_pw, abs((1-battery_instant_power/abs(battery_instant_power))*battery_instant_power/2) AS to_pw, abs((1+site_instant_power/abs(site_instant_power))*site_instant_power/2) AS from_grid, abs((1-site_instant_power/abs(site_instant_power))*site_instant_power/2) AS to_grid, percentage FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     {
#         'name': 'cq_autogen_current',
#         'resample': '',
#         'select': 'SELECT mean(home) AS home_current, mean(solar) AS solar_current, mean(pw) AS pw_current, mean(grid) AS grid_current',
#         'into': 'powerwall.autogen.:MEASUREMENT',
#         'from': 'SELECT load_instant_total_current AS home, solar_instant_total_current AS solar, battery_instant_total_current AS pw, site_instant_total_current AS grid FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     {
#         'name': 'cq_autogen_voltage',
#         'resample': '',
#         'select': 'SELECT mean(home) AS home_voltage, mean(solar) AS solar_voltage, mean(pw) AS pw_voltage, mean(grid) AS grid_voltage',
#         'into': 'powerwall.autogen.:MEASUREMENT',
#         'from': 'SELECT load_instant_average_voltage AS home, solar_instant_average_voltage AS solar, battery_instant_average_voltage AS pw, site_instant_average_voltage AS grid FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     {
#         'name': 'cq_kwh',
#         'resample': 'RESAMPLE EVERY 1m',
#         'select': 'SELECT integral(home)/1000/3600 AS home, integral(solar)/1000/3600 AS solar, integral(from_pw)/1000/3600 AS from_pw, integral(to_pw)/1000/3600 AS to_pw, integral(from_grid)/1000/3600 AS from_grid, integral(to_grid)/1000/3600 AS to_grid',
#         'into': 'powerwall.kwh.:MEASUREMENT',
#         'from': 'autogen.http',
#         'group_by': "time(1h), month, year tz('America/Los_Angeles')",
#         'fill': ''
#     },
#     {
#         'name': 'cq_daily',
#         'resample': 'RESAMPLE EVERY 1h',
#         'select': 'SELECT sum(home) AS home, sum(solar) AS solar, sum(from_pw) AS from_pw, sum(to_pw) AS to_pw, sum(from_grid) AS from_grid, sum(to_grid) AS to_grid',
#         'into': 'powerwall.daily.:MEASUREMENT',
#         'from': 'powerwall.kwh.http',
#         'group_by': "time(1d), month, year tz('America/Los_Angeles')",
#         'fill': ''
#     },
#     {
#         'name': 'cq_monthly',
#         'resample': 'RESAMPLE EVERY 1h',
#         'select': 'SELECT sum(home) AS home, sum(solar) AS solar, sum(from_pw) AS from_pw, sum(to_pw) AS to_pw, sum(from_grid) AS from_grid, sum(to_grid) AS to_grid',
#         'into': 'powerwall.monthly.:MEASUREMENT',
#         'from': 'powerwall.daily.http',
#         'group_by': 'time(365d), month, year',
#         'fill': ''
#     },
#     {
#         'name': 'cq_pw_temps',
#         'resample': '',
#         'select': 'SELECT mean(PW1_temp) AS PW1_temp, mean(PW2_temp) AS PW2_temp, mean(PW3_temp) AS PW3_temp, mean(PW4_temp) AS PW4_temp, mean(PW5_temp) AS PW5_temp, mean(PW6_temp) AS PW6_temp',
#         'into': 'powerwall.pwtemps.:MEASUREMENT',
#         'from': 'SELECT PW1_temp, PW2_temp, PW3_temp, PW4_temp, PW5_temp, PW6_temp FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     {
#         'name': 'cq_pw_tempsb',
#         'resample': '',
#         'select': 'SELECT mean(PW7_temp) AS PW7_temp, mean(PW8_temp) AS PW8_temp, mean(PW9_temp) AS PW9_temp, mean(PW10_temp) AS PW10_temp, mean(PW11_temp) AS PW11_temp, mean(PW12_temp) AS PW12_temp',
#         'into': 'powerwall.pwtemps.:MEASUREMENT',
#         'from': 'SELECT PW7_temp, PW8_temp, PW9_temp, PW10_temp, PW11_temp, PW12_temp FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
    
#     {
#         'name': 'cq_strings',
#         'resample': '',
#         'select': 'SELECT mean(A_Current) AS A_Current, mean(A_Power) AS A_Power, mean(A_Voltage) AS A_Voltage, mean(B_Current) AS B_Current, mean(B_Power) AS B_Power, mean(B_Voltage) AS B_Voltage, mean(C_Current) AS C_Current, mean(C_Power) AS C_Power, mean(C_Voltage) AS C_Voltage, mean(D_Current) AS D_Current, mean(D_Power) AS D_Power, mean(D_Voltage) AS D_Voltage',
#         'into': 'powerwall.strings.:MEASUREMENT',
#         'from': 'SELECT A_Current, A_Power, A_Voltage, B_Current, B_Power, B_Voltage, C_Current, C_Power, C_Voltage, D_Current, D_Power, D_Voltage FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     {
#         'name': 'cq_strings1',
#         'resample': '',
#         'select': 'SELECT mean(A1_Current) AS A1_Current, mean(A1_Power) AS A1_Power, mean(A1_Voltage) AS A1_Voltage, mean(B1_Current) AS B1_Current, mean(B1_Power) AS B1_Power, mean(B1_Voltage) AS B1_Voltage, mean(C1_Current) AS C1_Current, mean(C1_Power) AS C1_Power, mean(C1_Voltage) AS C1_Voltage, mean(D1_Current) AS D1_Current, mean(D1_Power) AS D1_Power, mean(D1_Voltage) AS D1_Voltage',
#         'into': 'powerwall.strings.:MEASUREMENT',
#         'from': 'SELECT A1_Current, A1_Power, A1_Voltage, B1_Current, B1_Power, B1_Voltage, C1_Current, C1_Power, C1_Voltage, D1_Current, D1_Power, D1_Voltage FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     # ... (cq_strings2 to cq_strings5 follow the same pattern)
#     {
#         'name': 'cq_strings6',
#         'resample': '',
#         'select': 'SELECT mean(E1_Current) AS E1_Current, mean(E1_Power) AS E1_Power, mean(E1_Voltage) AS E1_Voltage, mean(F1_Current) AS F1_Current, mean(F1_Power) AS F1_Power, mean(F1_Voltage) AS F1_Voltage',
#         'into': 'powerwall.strings.:MEASUREMENT',
#         'from': 'SELECT E1_Current, E1_Power, E1_Voltage, F1_Current, F1_Power, F1_Voltage FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     # ... (cq_strings7 to cq_strings11 follow the same pattern)
#     {
#         'name': 'cq_inverters',
#         'resample': '',
#         'select': 'SELECT mean(Inverter1) AS Inverter1, mean(Inverter2) AS Inverter2, mean(Inverter3) AS Inverter3, mean(Inverter4) AS Inverter4',
#         'into': 'powerwall.strings.:MEASUREMENT',
#         'from': 'SELECT A_Power+B_Power+C_Power+D_Power+E_Power+F_Power AS Inverter1, A1_Power+B1_Power+C1_Power+D1_Power+E1_Power+F1_Power AS Inverter2, A2_Power+B2_Power+C2_Power+D2_Power+E2_Power+F2_Power AS Inverter3, A3_Power+B3_Power+C3_Power+D3_Power+E3_Power+F3_Power AS Inverter4 FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     {
#         'name': 'cq_inverters1',
#         'resample': '',
#         'select': 'SELECT mean(Inverter5) AS Inverter5, mean(Inverter6) AS Inverter6',
#         'into': 'powerwall.strings.:MEASUREMENT',
#         'from': 'SELECT A4_Power+B4_Power+C4_Power+D4_Power+E4_Power+F4_Power AS Inverter5, A5_Power+B5_Power+C5_Power+D5_Power+E5_Power+F5_Power AS Inverter6 FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     # ... (cq_vitals1 to cq_vitals12 follow similar patterns)
#     {
#         'name': 'cq_grid',
#         'resample': 'RESAMPLE FOR 2m',
#         'select': 'SELECT min(grid_status) AS grid_status',
#         'into': 'powerwall.grid.:MEASUREMENT',
#         'from': 'SELECT grid_status FROM raw.http',
#         'group_by': 'time(1m), month, year',
#         'fill': 'fill(linear)'
#     },
#     # ... (cq_pod1 to cq_pod4 follow similar patterns)
#     {
#         'name': 'cq_alerts',
#         'resample': 'RESAMPLE FOR 2m',
#         'select': 'SELECT max(*)',
#         'into': 'powerwall.alerts.:MEASUREMENT',
#         'from': 'SELECT * FROM raw.alerts',
#         'group_by': 'time(1m), month, year',
#         'fill': ''
#     }
# ]



# string_queries = [
#     {
#         "name": "cq_strings",
#         "fields": [
#             "A_Current", "A_Power", "A_Voltage",
#             "B_Current", "B_Power", "B_Voltage",
#             "C_Current", "C_Power", "C_Voltage",
#             "D_Current", "D_Power", "D_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings1",
#         "fields": [
#             "A1_Current", "A1_Power", "A1_Voltage",
#             "B1_Current", "B1_Power", "B1_Voltage",
#             "C1_Current", "C1_Power", "C1_Voltage",
#             "D1_Current", "D1_Power", "D1_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings2",
#         "fields": [
#             "A2_Current", "A2_Power", "A2_Voltage",
#             "B2_Current", "B2_Power", "B2_Voltage",
#             "C2_Current", "C2_Power", "C2_Voltage",
#             "D2_Current", "D2_Power", "D2_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings3",
#         "fields": [
#             "A3_Current", "A3_Power", "A3_Voltage",
#             "B3_Current", "B3_Power", "B3_Voltage",
#             "C3_Current", "C3_Power", "C3_Voltage",
#             "D3_Current", "D3_Power", "D3_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings4",
#         "fields": [
#             "A4_Current", "A4_Power", "A4_Voltage",
#             "B4_Current", "B4_Power", "B4_Voltage",
#             "C4_Current", "C4_Power", "C4_Voltage",
#             "D4_Current", "D4_Power", "D4_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings5",
#         "fields": [
#             "A5_Current", "A5_Power", "A5_Voltage",
#             "B5_Current", "B5_Power", "B5_Voltage",
#             "C5_Current", "C5_Power", "C5_Voltage",
#             "D5_Current", "D5_Power", "D5_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings6",
#         "fields": [
#             "E1_Current", "E1_Power", "E1_Voltage",
#             "F1_Current", "F1_Power", "F1_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings7",
#         "fields": [
#             "E2_Current", "E2_Power", "E2_Voltage",
#             "F2_Current", "F2_Power", "F2_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings8",
#         "fields": [
#             "E3_Current", "E3_Power", "E3_Voltage",
#             "F3_Current", "F3_Power", "F3_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings9",
#         "fields": [
#             "E4_Current", "E4_Power", "E4_Voltage",
#             "F4_Current", "F4_Power", "F4_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings10",
#         "fields": [
#             "E5_Current", "E5_Power", "E5_Voltage",
#             "F5_Current", "F5_Power", "F5_Voltage",
#         ]
#     },
#     {
#         "name": "cq_strings11",
#         "fields": [
#             "E_Current", "E_Power", "E_Voltage",
#             "F_Current", "F_Power", "F_Voltage",
#         ]
#     },
# ]
