<div class="macro"><div>🥑</div><b>{total['fat_g']:.0f} g</b><div>Fat</div></div>
<div class="macro"><div>🥦</div><b>{total['fiber_g']:.0f} g</b><div>Fiber</div></div></div>''', unsafe_allow_html=True)
            st.caption(f"Sugar: {total['sugar_g']:.0f} g · Sodium: {total['sodium_mg']:.0f} mg")
            st.plotly_chart(macro_chart(total["protein_g"], total["carbs_g"], total["fat_g"], total["calories"]), use_container_width=True, config={"displayModeBar": False}, key="scan_macro_chart")
            if result.get("items"):
                st.markdown("#### 🧾 Item breakdown")
                items_df = pd.DataFrame(result["items"]).rename(columns={"name":"Item", "portion":"Portion", "calories":"kcal", "protein_g":"Protein (g)", "carbs_g":"Carbs (g)", "fat_g":"Fat (g)"})
                st.dataframe(items_df, hide_index=True, use_container_width=True)
            if result.get("tips"):
                st.markdown("#### 💡 Smart tips")
                for tip in result["tips"][:3]:
                    st.write(f"- {tip}")
            already_added = result["id"] in st.session_state.added_ids
            hour = dt.datetime.now().hour
            default_meal = 0 if hour < 11 else 1 if hour < 16 else 2 if hour < 19 else 3
            meal_col, button_col = st.columns([1, 1])
            meal_type = meal_col.selectbox("Meal type", MEAL_TYPES, index=default_meal, key="meal_type_select")
            if button_col.button("✅ Added to log" if already_added else "➕ Add to today's log", disabled=already_added, type="primary"):
                st.session_state.log.append({"id": result["id"], "time": dt.datetime.now().strftime("%H:%M"), "meal": meal_type, "food": result.get("meal_name") or "Meal", "calories": total["calories"], "protein_g": total["protein_g"], "carbs_g": total["carbs_g"], "fat_g": total["fat_g"], "fiber_g": total["fiber_g"]})
                st.session_state.added_ids.add(result["id"])
                st.toast("Meal added to your log!")
                st.rerun()

with tab_log:
    st.markdown("### 📊 Today's nutrition")
    current_log = pd.DataFrame(st.session_state.log)
    if current_log.empty:
        st.info("Your log is empty. Scan a meal and tap Add to today's log.")
    else:
        sums = current_log[["calories", "protein_g", "carbs_g", "fat_g"]].sum()
        col_a, col_b = st.columns([1.1, 1])
        with col_a:
            for label, value, goal_value, unit in [("🔥 Calories", sums["calories"], target, "kcal"), ("🥩 Protein", sums["protein_g"], t_pro, "g"), ("🌾 Carbs", sums["carbs_g"], t_carb, "g"), ("🥑 Fat", sums["fat_g"], t_fat, "g")]:
                ratio = value / goal_value if goal_value else 0
                st.markdown(f"**{label}** — {value:,.0f} / {goal_value:,} {unit}")
                st.progress(min(max(ratio, 0.0), 1.0))
        with col_b:
            st.plotly_chart(macro_chart(sums["protein_g"], sums["carbs_g"], sums["fat_g"], sums["calories"]), use_container_width=True, config={"displayModeBar": False}, key="log_macro_chart")
        st.markdown("#### 🍽️ Meals")
        for index, row in enumerate(st.session_state.log):
            item_col, del_col = st.columns([6, 1])
            item_col.markdown(f'<div class="card"><b>{row["meal"]} · {row["food"]}</b><br><small>🕒 {row["time"]} · 🔥 {row["calories"]:.0f} kcal · P {row["protein_g"]:.0f}g · C {row["carbs_g"]:.0f}g · F {row["fat_g"]:.0f}g</small></div>', unsafe_allow_html=True)
            if del_col.button("🗑️", key=f"delete_{row['id']}_{index}", help="Remove this meal"):
                st.session_state.log.pop(index)
                st.rerun()
        by_meal = current_log.groupby("meal", as_index=False)["calories"].sum()
        bar = go.Figure(go.Bar(x=by_meal["meal"], y=by_meal["calories"], marker=dict(color="#22c55e"), text=by_meal["calories"].round(0), textposition="outside"))
        bar.update_layout(height=280, margin=dict(t=25, b=10, l=10, r=10), yaxis_title="kcal", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(bar, use_container_width=True, config={"displayModeBar": False}, key="meal_calorie_bar")
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Download log (CSV)", current_log.drop(columns=["id"], errors="ignore").to_csv(index=False), file_name=f"cal_ai_log_{dt.date.today()}.csv", mime="text/csv")
        if d2.button("🧹 Clear today's log"):
            st.session_state.log = []
            st.session_state.added_ids = set()
            st.rerun()
        st.caption("Your meal log is kept in the current Streamlit session. Download it before closing the app.")

with tab_fit:
    plan = EXERCISE_PLANS[category]
    col1, col2 = st.columns([1, 1.2], gap="large")
    with col1:
        st.markdown("### ⚖️ Your BMI")
        gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=round(bmi, 1),
            number=dict(font=dict(size=38)),
            gauge=dict(
                axis=dict(range=[10, 45]),
                bar=dict(color=category_color),
                bgcolor="rgba(0,0,0,0)",
                steps=[
                    dict(range=[10, 18.5], color="rgba(59,130,246,.2)"),
                    dict(range=[18.5, 25], color="rgba(34,197,94,.2)"),
                    dict(range=[25, 30], color="rgba(245,158,11,.2)"),
                    dict(range=[30, 45], color="rgba(239,68,68,.2)"),
                ],
            ),
        ))
        gauge.update_layout(height=240, margin=dict(t=20,b=0,l=20,r=20), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(gauge, use_container_width=True, config={"displayModeBar": False}, key="bmi_gauge")
        low, high = 18.5 * (height / 100) ** 2, 24.9 * (height / 100) ** 2
        st.info(f"Category: **{category}** · Reference healthy-weight range for this height: {low:.1f}–{high:.1f} kg")
    with col2:
        st.markdown("### 🔢 Your numbers")
        a, b, c = st.columns(3)
        a.metric("BMR", f"{bmr:,.0f} kcal")
        b.metric("TDEE", f"{tdee:,.0f} kcal")
        c.metric("Target", f"{target:,} kcal")
        a, b, c = st.columns(3)
        a.metric("🥩 Protein", f"{t_pro} g")
        b.metric("🌾 Carbs", f"{t_carb} g")
        c.metric("🥑 Fat", f"{t_fat} g")
        st.markdown(f'<div class="card"><b>🎯 Focus: {plan["focus"]}</b><br>{plan["advice"]}</div>', unsafe_allow_html=True)
    if category == "Obese":
        st.warning("Consider consulting a healthcare professional before starting a new exercise program.")
    st.markdown("### 🏋️ Suggested activities  ⚡")
    ex_cols = st.columns(2)
    for index, (emoji, exercise, instructions, minutes) in enumerate(EXERCISES[category]):
        ex_cols[index % 2].markdown(f'<div class="card"><b>{emoji} {exercise}</b><br><small>{instructions}</small><br><small>⏱ Suggested duration: {minutes} min</small></div>', unsafe_allow_html=True)
    st.markdown("### 📅 Your weekly movement plan")
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    schedule = pd.DataFrame({"Day": days, "Plan": plan["weekly"]})
    st.dataframe(schedule, hide_index=True, use_container_width=True)

with tab_about:
    st.markdown("""
### 🧠 How Cal AI works
1. **Capture:** take a meal photo or upload one.
2. **Recognise:** Google Gemini Vision identifies visible foods and estimates portions.
3. **Estimate:** calories, protein, carbs, fat, fiber, sugar and sodium are estimated.
4. **Track:** add meals to your current session log and compare them with your daily target.
5. **Move:** view general exercise ideas based on your BMI category.

### 📐 Formulas
- **BMI** = weight (kg) ÷ height (m)²
- **BMR** = Mifflin–St Jeor estimate
- **TDEE** = BMR × activity factor

### ⚠️ Important note
Nutrition estimates from photos can be inaccurate, especially when portion sizes, oils, sauces, and ingredients are hidden. BMI is a screening measure, not a diagnosis. This app is for general wellness and is not medical advice.
""")

st.markdown('<p style="text-align:center;opacity:.6;font-size:.8rem;margin-top:2rem">🥑 Eat well · 💪 Move daily · Made with ❤️ using Streamlit and Google Gemini · Cal AI</p>', unsafe_allow_html=True)
