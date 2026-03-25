%%writefile app.py
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import timedelta
import numpy as np

# -------------------------------------------------
# PAGE SETUP
# -------------------------------------------------
st.set_page_config(page_title="Coffee Shop Analysis Dashboard", layout="wide")
st.title("☕ Coffee Shop Analysis")
st.caption("By Mithesh Ramachandran")

# -------------------------------------------------
# LOAD & CLEAN DATA
# -------------------------------------------------
path = "Coffeedata_clean50k.xlsx"
df = pd.read_excel(path)
df["transaction_date"] = pd.to_datetime(df["transaction_date"])
df["hour"] = pd.to_datetime(df["transaction_time"], format="%H:%M:%S", errors="coerce").dt.hour
df["sales"] = df["transaction_qty"] * df["unit_price"]
df["week"] = df["transaction_date"].dt.isocalendar().week.values
df["weekday"] = df["transaction_date"].dt.day_name()

# ensure base_product column exists
if "base_product" not in df.columns:
    df["base_product"] = (
        df["product_detail"]
        .str.replace(r"\b(Sm|Rg|Lg)\b", "", regex=True)
        .str.strip()
    )

stores = sorted(df["store_location"].dropna().unique().tolist())
selected_stores = st.sidebar.multiselect("Select store(s)", stores, default=stores)
metric_type = st.sidebar.radio("Metric Type", ["Sales", "Transactions"])
filtered = df[df["store_location"].isin(selected_stores)]

# -------------------------------------------------
# CREATE TABS
# -------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(["📊 Live Simulation", "📅 2023 Overview", "📈 Projections", "Simulation"])

# -------------------------------------------------
# TAB 1: LIVE SIMULATION
# -------------------------------------------------
with tab1:

    # -------------------------------------------------
    # PRECOMPUTE DAYS (FEB 11 → FEB 18 + FEB 19)
    # -------------------------------------------------
    if "precomputed" not in st.session_state:
        base_day = pd.to_datetime("2023-02-18").date()
        days = [base_day - timedelta(days=i) for i in range(7, -1, -1)]  # 11–18 Feb
        days += [base_day + timedelta(days=1)]  # add 19 Feb (next day)
        summary = {}

        for day in days:
            day_df = filtered[filtered["transaction_date"].dt.date == day].copy()
            if day_df.empty:
                continue

            hourly = []
            for h in range(0, 24):
                hour_df = day_df[day_df["hour"] <= h]
                if hour_df.empty:
                    continue

                metrics = {
                    "day": day,
                    "hour": h,
                    "sales": hour_df["sales"].sum(),
                    "transactions": hour_df["transaction_id"].nunique(),
                    "upt": hour_df["transaction_qty"].sum() / max(hour_df["transaction_id"].nunique(), 1),
                    "store_perf": hour_df.groupby("store_location", as_index=False)["sales"].sum(),
                    # use base_product to combine sizes
                    "top_skus": hour_df.groupby("base_product", as_index=False)["sales"]
                        .sum().sort_values("sales", ascending=False).head(5),
                    "bottom_skus": hour_df.groupby("base_product", as_index=False)["sales"]
                        .sum().sort_values("sales", ascending=True).head(5),
                }
                hourly.append(metrics)

            summary[str(day)] = hourly

        st.session_state["precomputed"] = summary
        st.session_state["sim_day"] = str(base_day)
        st.session_state["sim_hour"] = 6

    # -------------------------------------------------
    # HELPERS
    # -------------------------------------------------
    def get_current():
        day_key = st.session_state["sim_day"]
        hour_val = st.session_state["sim_hour"]
        entries = [e for e in st.session_state["precomputed"][day_key] if e["hour"] <= hour_val]
        return entries[-1] if entries else None

    def render(current):
        if not current:
            st.warning("No data for this hour.")
            return

        # -------------------------------------------------
        # METRICS + 7-DAY TICKERS
        # -------------------------------------------------
        metric_area.empty()
        with metric_area.container():
            st.subheader("Performance Metrics")

            # --- week-ago same time comparison ---
            hour_val = current["hour"]
            day_dt = pd.to_datetime(st.session_state["sim_day"]).date()
            week_ago_date = str(day_dt - timedelta(days=7))

            if week_ago_date in st.session_state["precomputed"]:
                prev_entries = [e for e in st.session_state["precomputed"][week_ago_date] if e["hour"] == hour_val]
                prev_7d = prev_entries[-1] if prev_entries else None
            else:
                prev_7d = None

            def pct_change(curr, prev):
                if not prev or prev == 0:
                    return 0.0
                return (curr - prev) / prev * 100

            sales_change = pct_change(current["sales"], prev_7d["sales"] if prev_7d else 0)
            tx_change = pct_change(current["transactions"], prev_7d["transactions"] if prev_7d else 0)
            upt_change = pct_change(current["upt"], prev_7d["upt"] if prev_7d else 0)

            c1, c2, c3 = st.columns(3)
            c1.metric("Sales So Far", f"${current['sales']:,.0f}", f"{sales_change:+.1f}% vs 7 d ago")
            c2.metric("Transactions So Far", f"{current['transactions']:,}", f"{tx_change:+.1f}% vs 7 d ago")
            c3.metric("UPT", f"{current['upt']:.2f}", f"{upt_change:+.1f}% vs 7 d ago")

        # -------------------------------------------------
        # STORE CHART
        # -------------------------------------------------
        chart_area.empty()
        with chart_area.container():
            st.subheader(f"Store-wise {metric_type} Performance")
            store_perf = current["store_perf"]
            if metric_type == "Transactions":
                day = pd.to_datetime(st.session_state["sim_day"]).date()
                store_perf = filtered[filtered["transaction_date"].dt.date == day]
                store_perf = (
                    store_perf[store_perf["hour"] <= current["hour"]]
                    .groupby("store_location", as_index=False)["transaction_id"]
                    .nunique()
                )
                store_perf.rename(columns={"transaction_id": "transactions"}, inplace=True)
                y_col, y_label = "transactions", "Transactions"
            else:
                y_col, y_label = "sales", "Sales ($)"

            fig = px.bar(store_perf, x="store_location", y=y_col, text=y_col,
                         color=y_col, color_continuous_scale="OrRd", labels={y_col: y_label})
            fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
            st.plotly_chart(fig, use_container_width=True)

        # -------------------------------------------------
        # TOP / BOTTOM PRODUCTS
        # -------------------------------------------------
        table_area.empty()
        with table_area.container():
            st.subheader("Product Performance – So Far (by Base Product)")
            left, right = st.columns(2)
            left.write("🔥 Top Performing SKUs")
            left.dataframe(current["top_skus"], hide_index=True)
            right.write("🧊 Bottom Performing SKUs")
            right.dataframe(current["bottom_skus"], hide_index=True)

        # -------------------------------------------------
        # TOP COMBO PER STORE
        # -------------------------------------------------
        st.divider()
        st.subheader("🥤 Top Customizations/Combos per Store")

        # limit to the current simulated day
        sim_day = pd.to_datetime(st.session_state["sim_day"]).date()
        day_data = filtered[filtered["transaction_date"].dt.date == sim_day]

        # find combos that contain "with" or "and"
        combo_mask = (
            day_data["actual_order"].notna() &
            day_data["actual_order"].str.contains(r"\b(with|and)\b", case=False, regex=True)
        )

        combo_df = (
            day_data[combo_mask]
            .groupby(["store_location", "actual_order"])
            .size()
            .reset_index(name="count")
        )

        # pick most frequent combo per store
        top_combos = (
            combo_df
            .sort_values(["store_location", "count"], ascending=[True, False])
            .groupby("store_location")
            .head(1)
        )

        st.dataframe(top_combos, hide_index=True)

    # -------------------------------------------------
    # LAYOUT CONTROLS
    # -------------------------------------------------
    col_a, col_b, col_c = st.columns([3, 1, 1])
    with col_a:
        st.write(f"📆 {st.session_state['sim_day']} — ⏰ Hour {st.session_state['sim_hour']}:00")
    with col_b:
        if st.button("Next Hour ▶️"):
            hours = [e["hour"] for e in st.session_state["precomputed"][st.session_state["sim_day"]]]
            idx = hours.index(st.session_state["sim_hour"]) if st.session_state["sim_hour"] in hours else 0
            st.session_state["sim_hour"] = hours[min(idx + 1, len(hours) - 1)]
    with col_c:
        if st.button("➡️ Next Day"):
            next_day = pd.to_datetime(st.session_state["sim_day"]).date() + timedelta(days=1)
            if str(next_day) in st.session_state["precomputed"]:
                st.session_state["sim_day"] = str(next_day)
                st.session_state["sim_hour"] = 6

    metric_area = st.empty()
    chart_area = st.empty()
    table_area = st.empty()

    # -------------------------------------------------
    # RENDER
    # -------------------------------------------------
    render(get_current())

# -------------------------------------------------
# TAB 2: 2023 PATTERNS (Weeks 1–8, Hours 5–19)
# -------------------------------------------------
with tab2:
    st.subheader("📅 2023 Patterns – Weekly Trends (Jan–Mar Range)")

    # restrict to 2023 up to March 24
    df_2023 = filtered[
        (filtered["transaction_date"].dt.year == 2023)
        & (filtered["transaction_date"] <= "2023-03-24")
    ].copy()

    # clean week + weekday
    df_2023 = df_2023[df_2023["transaction_date"].notna()].copy()
    df_2023["week"] = df_2023["transaction_date"].dt.isocalendar().week.astype(int)
    df_2023["weekday"] = df_2023["transaction_date"].dt.day_name()

    weekday_order = ["Monday", "Tuesday", "Wednesday",
                     "Thursday", "Friday", "Saturday", "Sunday"]
    df_2023 = df_2023[df_2023["weekday"].notna()]
    df_2023["weekday"] = pd.Categorical(
        df_2023["weekday"], categories=weekday_order, ordered=True
    )

    # -------------------------------------------------
    # 1. Week vs Weekday Heatmap (Full 8x7 grid)
    # -------------------------------------------------
    st.markdown("### 🗓️ Week vs Weekday Performance")

    g = df_2023.groupby(["week", "weekday"])
    weekly_heat = g[["sales"]].sum().reset_index()
    weekly_heat["transaction_id"] = g["transaction_id"].nunique().values

    # create full grid
    import itertools
    all_combos = pd.DataFrame(
        list(itertools.product(range(1, 9), weekday_order)),
        columns=["week", "weekday"]
    )
    weekly_heat = (
        all_combos.merge(weekly_heat, on=["week", "weekday"], how="left")
        .fillna({"sales": 0, "transaction_id": 0})
    )

    z_col = "sales" if metric_type == "Sales" else "transaction_id"

    fig_weekday = px.density_heatmap(
        weekly_heat,
        x="week",
        y="weekday",
        z=z_col,
        color_continuous_scale="YlOrRd",
        range_x=[1, 8],
        range_color=[2000, 6000] if metric_type == "Sales" else None,  # fixed 23–25 k
        labels={"week": "Week #", "weekday": "Day of Week", z_col: metric_type},
        title=f"{metric_type} Intensity by Week and Weekday (Weeks 1–8)"
    )
    fig_weekday.update_xaxes(dtick=1)
    st.plotly_chart(fig_weekday, use_container_width=True)

    # -------------------------------------------------
    # 2. Time-of-Day Heatmap (2-Hour Bins, 5–19)
    # -------------------------------------------------
    st.markdown("### ☕ Hourly Category Performance (2-Hour Bins 5–19)")

    # define bins explicitly from 5 to 19
    bins = list(range(5, 21, 2))  # [5,7,9,...,19]
    labels = [f"{i}-{i+2}" for i in bins[:-1]]

    df_2023["hour_bin"] = pd.cut(
        df_2023["hour"].fillna(5).clip(lower=5, upper=19),
        bins=bins,
        labels=labels,
        include_lowest=True,
        right=False
    )

    g2 = df_2023.groupby(["hour_bin", "product_category"])
    hour_cat = g2[["sales"]].sum().reset_index()
    hour_cat["transaction_id"] = g2["transaction_id"].nunique().values

    z2 = "sales" if metric_type == "Sales" else "transaction_id"

    fig_hourcat = px.density_heatmap(
        hour_cat,
        x="hour_bin",
        y="product_category",
        z=z2,
        color_continuous_scale="Blues",
        labels={
            "hour_bin": "Hour Range (2-hour slots)",
            "product_category": "Category",
            z2: metric_type,
        },
        title="Category Activity by 2-Hour Intervals (5–19 hrs)"
    )
    st.plotly_chart(fig_hourcat, use_container_width=True)

    # -------------------------------------------------
    # 3. Weekday Average Chart
    # -------------------------------------------------
    st.markdown("### 📆 Average Performance by Weekday")

    g3 = df_2023.groupby("weekday")
    weekday_avg = g3[["sales"]].sum().reset_index()
    weekday_avg["transaction_id"] = g3["transaction_id"].nunique().values
    weekday_avg = weekday_avg.sort_values("weekday")

    y_col = "sales" if metric_type == "Sales" else "transaction_id"
    fig_bar = px.bar(
        weekday_avg,
        x="weekday",
        y=y_col,
        text=y_col,
        color=y_col,
        color_continuous_scale="OrRd",
        labels={"weekday": "Day of Week", y_col: metric_type},
        title=f"Average {metric_type} by Weekday (Weeks 1–8)"
    )
    fig_bar.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    st.plotly_chart(fig_bar, use_container_width=True)

    st.caption("Sidebar filters apply to all tabs (Store + Metric Type).")

# -------------------------------------------------
# TAB 3: 2023 FORECASTS (Weeks 1–11)
# -------------------------------------------------
with tab3:
    st.subheader("📈 2023 Forecasts (Weeks 1–11)")

    # Filter 2023 data up to week 11
    df_2023 = filtered[
        (filtered["transaction_date"].dt.year == 2023)
        & (filtered["transaction_date"].dt.isocalendar().week <= 11)
    ].copy()
    df_2023["week"] = df_2023["transaction_date"].dt.isocalendar().week.astype(int)

    # Weekly aggregation
    weekly = (
        df_2023.groupby(["store_location", "week"], as_index=False)
        .agg({
            "sales": "sum",
            "transaction_id": "nunique",
            "transaction_qty": "sum"
        })
        .rename(columns={"transaction_id": "transactions"})
    )
    weekly["upt"] = (
        weekly["transaction_qty"] / weekly["transactions"].replace(0, np.nan)
    )

    metric_choice = st.radio(
        "Select Metric", ["Sales", "Transactions", "UPT"], horizontal=True
    )

    # Plot each store separately
    for store in sorted(weekly["store_location"].unique()):
        subset = weekly[weekly["store_location"] == store].sort_values("week")
        subset["sma4"] = (
            subset[metric_choice.lower()].rolling(4, min_periods=1).mean()
        )

        st.markdown(f"#### {store}")
        fig = px.line(
            subset,
            x="week",
            y=metric_choice.lower(),
            markers=True,
            title=f"{metric_choice} Trend – {store}",
            color_discrete_sequence=["#FF4B4B"]
        )

        # Add 4-week simple moving average
        fig.add_scatter(
            x=subset["week"],
            y=subset["sma4"],
            mode="lines",
            name="4-week SMA",
            line=dict(color="orange", dash="dot")
        )

        # Annotate best / worst
        best_idx = subset[metric_choice.lower()].idxmax()
        worst_idx = subset[metric_choice.lower()].idxmin()

        if pd.notna(best_idx):
            fig.add_annotation(
                x=subset.loc[best_idx, "week"],
                y=subset.loc[best_idx, metric_choice.lower()],
                text="🏆 Best Week",
                showarrow=True,
                arrowhead=2
            )
        if pd.notna(worst_idx):
            fig.add_annotation(
                x=subset.loc[worst_idx, "week"],
                y=subset.loc[worst_idx, metric_choice.lower()],
                text="📉 Worst Week",
                showarrow=True,
                arrowhead=2
            )

        fig.update_layout(
            xaxis_title="Week #",
            yaxis_title=metric_choice,
            xaxis=dict(range=[1, 11])
        )
        st.plotly_chart(fig, use_container_width=True)

    st.caption("Shows weekly performance up to week 11 with 4-week moving averages.")

# -------------------------------------------------
# TAB 4: ITEM-SPECIFIC IMPACT SIMULATION (DYNAMIC SUBSTITUTION)
# -------------------------------------------------
with tab4:
    st.subheader("💸 Item-Specific Impact Simulation (Weeks 1–11, Dynamic Substitution)")

    # limit to weeks 1–11
    df_2023 = filtered[
        (filtered["transaction_date"].dt.year == 2023)
        & (filtered["transaction_date"].dt.isocalendar().week <= 11)
    ].copy()
    df_2023["week"] = df_2023["transaction_date"].dt.isocalendar().week.astype(int)

    # item list
    item_sales = (
        df_2023.groupby("base_product", as_index=False)
        .agg({"sales": "sum", "transaction_qty": "sum"})
        .sort_values("sales")
    )

    st.markdown("### Select Item and Assumptions")
    ingredient = st.selectbox("Ingredient / Base Product", item_sales["base_product"])

    item_df = df_2023[df_2023["base_product"] == ingredient].copy()
    if item_df.empty:
        st.warning("No transactions found for this item.")
        st.stop()

    # average selling and cost per unit
    avg_price = (
        item_df["sales"].sum() / item_df["transaction_qty"].sum()
        if item_df["transaction_qty"].sum() > 0 else 0
    )
    cost_per_unit = st.number_input(
        "Sourcing Cost per Unit ($)",
        min_value=0.0,
        value=float(round(avg_price * 0.8, 2)),  # assume 80% of price by default
        step=0.1
    )

    substitution_rate = st.slider(
        "Long-run Substitution Rate (%) – by week 6–8",
        0, 100, 40,
        help="Share of customers who eventually switch to other products."
    )
    inv_multiplier = st.number_input(
        "Inventory Multiplier (× avg daily orders on hand)",
        min_value=1.0, value=1.3, step=0.1
    )

    # baseline weekly profit
    weekly_item = (
        item_df.groupby("week", as_index=False)
        .agg({"transaction_qty": "sum", "sales": "sum"})
    )
    weekly_item["baseline_profit"] = (
        weekly_item["sales"] - weekly_item["transaction_qty"] * cost_per_unit
    )

    avg_daily_qty = item_df.groupby("transaction_date")["transaction_qty"].sum().mean()
    avg_weekly_qty = avg_daily_qty * 7
    profit_per_unit = avg_price - cost_per_unit

    # dynamic substitution curve (ramps up to final rate by week 6)
    weeks_total = 11
    ramp_weeks = min(6, weeks_total)
    sub_curve = np.linspace(0.1, substitution_rate / 100, ramp_weeks)
    if ramp_weeks < weeks_total:
        sub_curve = np.concatenate([
            sub_curve,
            np.full(weeks_total - ramp_weeks, substitution_rate / 100)
        ])

    # simulate
    results = []
    for w in range(1, weeks_total + 1):
        base_row = weekly_item[weekly_item["week"] == w]
        base_profit = base_row["baseline_profit"].values[0] if not base_row.empty else 0

        current_sub = sub_curve[w - 1]
        lost_rate = 1 - current_sub

        lost_qty = avg_weekly_qty * lost_rate
        cost_saved = lost_qty * cost_per_unit                # you don't buy these units
        substitute_gain = avg_weekly_qty * current_sub * profit_per_unit
        simulated_profit = cost_saved + substitute_gain

        results.append([w, base_profit, simulated_profit, current_sub * 100])

    sim_df = pd.DataFrame(results, columns=["Week", "Baseline Profit", "Simulated Profit", "Substitution %"])
    sim_df["Difference"] = sim_df["Simulated Profit"] - sim_df["Baseline Profit"]

    # table
    st.markdown(f"### 📊 {ingredient} – Profit Comparison (Weeks 1–11)")
    st.dataframe(
        sim_df.style.format({
            "Baseline Profit": "${:,.0f}",
            "Simulated Profit": "${:,.0f}",
            "Difference": "${:,.0f}",
            "Substitution %": "{:.0f}%"
        })
    )

    # plot
    fig = px.line(
        sim_df,
        x="Week",
        y=["Baseline Profit", "Simulated Profit"],
        markers=True,
        title=f"Weekly Profit Comparison for {ingredient}",
        labels={"value": "Profit ($)", "variable": "Scenario"},
        color_discrete_map={
            "Baseline Profit": "#2E86DE",
            "Simulated Profit": "#E45756"
        }
    )
    fig.add_hline(y=0, line_dash="dot", line_color="gray")
    st.plotly_chart(fig, use_container_width=True)

    # substitution curve overlay (optional small chart)
    with st.expander("Show substitution adoption curve"):
        fig2 = px.line(
            sim_df,
            x="Week",
            y="Substitution %",
            markers=True,
            title="Customer Adaptation to Ingredient Removal",
            labels={"Week": "Week", "Substitution %": "Customers Switching"}
        )
        st.plotly_chart(fig2, use_container_width=True)

    total_diff = sim_df["Difference"].sum()
    note = "gain" if total_diff > 0 else "loss"
    st.caption(
        f"Removing **{ingredient}** yields a total estimated **{note} of ${abs(total_diff):,.0f}** "
        f"over 11 weeks. Substitution starts low and rises to **{substitution_rate}%** by week 6."
    )
