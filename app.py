"""Cal AI — food photo calorie estimator and simple fitness dashboard.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py

For Streamlit Community Cloud, add GEMINI_API_KEY in App settings → Secrets.
"""
import io
import json
import re
import uuid
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageOps

try:
    from google import genai
    from google.genai import types
    GENAI_OK = True
except Exception:
    GENAI_OK = False

st.set_page_config(page_title="Cal AI · Food Calorie Scanner", page_icon="🥗", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] {font-family:'Poppins',sans-serif}
.block-container{padding-top:1.5rem;max-width:1250px}
.hero{background:linear-gradient(135deg,#0f9b8e,#22c55e 60%,#a3e635);border-radius:22px;padding:1.5rem 2rem;color:white;margin-bottom:1rem}
.hero h1{color:white;margin:0;font-weight:800}.hero p{color:white;margin:.3rem 0 0}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.7rem;margin-bottom:1rem}
.kpi{border-radius:16px;padding:1rem;color:white}.kpi .lbl{font-size:.75rem;text-transform:uppercase;opacity:.9}.kpi .val{font-size:1.6rem;font-weight:800}.g1{background:linear-gradient(135deg,#f97316,#fb923c)}.g2{background:linear-gradient(135deg,#6366f1,#8b5cf6)}.g3{background:linear-gradient(135deg,#0ea5e9,#22d3ee)}.g4{background:linear-gradient(135deg,#ec4899,#f43f5e)}
.card{border-radius:15px;padding:1rem;background:rgba(128,128,128,.07);border:1px solid rgba(128,128,128,.18);margin-bottom:.7rem}
.cal-card{background:linear-gradient(135deg,#111827,#374151);color:white;border-radius:20px;padding:1.3rem;margin:.7rem 0}.cal-big{font-size:2.6rem;font-weight:800}.macro-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem}.macro{text-align:center;border:1px solid rgba(128,128,128,.2);border-radius:14px;padding:.8rem}.macro b{font-size:1.3rem}
div.stButton>button,div.stDownloadButton>button{width:100%;border-radius:11px;font-weight:600}
@media(max-width:700px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.macro-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
""", unsafe_allow_html=True)

ACTIVITY = {
    "Sedentary (little / no exercise)": 1.2,
    "Lightly active (1–3 days/week)": 1.375,
    "Moderately active (3–5 days/week)": 1.55,
    "Very active (6–7 days/week)": 1.725,
    "Athlete (training 2x/day)": 1.9,
}
GOALS = {"Lose weight": -500, "Maintain weight": 0, "Gain muscle": 300}
MEAL_TYPES = ["🌅 Breakfast", "☀️ Lunch", "🍎 Snack", "🌙 Dinner"]
MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.0-flash"]
EXERCISE_PLANS = {
    "Underweight": {"focus": "Build muscle and strength", "advice": "Prioritize regular meals, adequate protein, progressive strength training, and recovery.", "weekly": ["Full-body strength", "Walk + mobility", "Upper-body strength", "Rest / mobility", "Lower-body strength", "Light walk", "Rest"]},
    "Normal": {"focus": "Maintain balanced fitness", "advice": "Combine regular cardio, strength training, sleep, and balanced meals.", "weekly": ["Run + core", "Lower-body strength", "Cardio + yoga", "Rest / walk", "Upper-body strength", "Cycling or walk", "Rest / stretch"]},
    "Overweight": {"focus": "Build consistency with low-impact activity", "advice": "Start at a manageable pace, gradually increase activity, and include strength work.", "weekly": ["Brisk walk", "Strength + stretch", "Cycling", "Walk", "Low-impact circuit", "Long walk or swim", "Rest"]},
    "Obese": {"focus": "Gentle, joint-friendly movement", "advice": "Start slowly and build gradually. Consider speaking with a healthcare professional before starting a new exercise plan.", "weekly": ["Comfortable walk", "Gentle strength", "Rest / mobility", "Short walk", "Chair strength", "Easy walk or swim", "Rest"]},
}
EXERCISES = {
    "Underweight": [("🏋️", "Bodyweight squats", "3 × 12 reps", 10), ("💪", "Push-ups", "3 × 8–12 reps", 8), ("🎒", "Rows", "3 × 10 reps", 10), ("🧘", "Mobility", "Easy recovery flow", 15)],
    "Normal": [("🏃", "Jogging", "Comfortable steady pace", 25), ("🏋️", "Squats and lunges", "3 × 12 reps", 12), ("💪", "Push-ups", "3 sets", 8), ("🧘", "Yoga / stretching", "Cool-down", 15)],
    "Overweight": [("🚶", "Brisk walking", "Comfortably challenging pace", 30), ("🚴", "Cycling", "Moderate resistance", 25), ("🪑", "Chair squats", "2–3 × 10 reps", 8), ("🧘", "Stretching", "Gentle full-body routine", 10)],
    "Obese": [("🚶", "Comfortable walk", "Build duration gradually", 15), ("🪑", "Chair sit-to-stands", "2 × 8 reps", 6), ("💪", "Wall push-ups", "2 × 8 reps", 5), ("🧘", "Chair yoga", "Gentle mobility", 10)],
}

for key, default in {"log": [], "result": None, "added_ids": set()}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def safe_num(value, default=0.0):
    try:
        if isinstance(value, str):
            value = re.sub(r"[^0-9.\-]", "", value)
        return float(value)
    except (TypeError, ValueError):
        return default


def calc_bmi(weight_kg, height_cm):
    h = height_cm / 100
    return weight_kg / (h * h) if h > 0 else 0.0


def bmi_category(bmi):
    if bmi < 18.5:
        return "Underweight", "#3b82f6"
    if bmi < 25:
        return "Normal", "#22c55e"
    if bmi < 30:
        return "Overweight", "#f59e0b"
    return "Obese", "#ef4444"


def calc_bmr(weight, height, age, gender):
    return 10 * weight + 6.25 * height - 5 * age + (5 if gender == "Male" else -161)


def macro_targets(target_kcal, weight, goal):
    protein = weight * (2.0 if goal != "Maintain weight" else 1.6)
    fat = target_kcal * 0.25 / 9
    carbs = max((target_kcal - protein * 4 - fat * 9) / 4, 50)
    return round(protein), round(carbs), round(fat)


def get_secret(name):
    try:
        return str(st.secrets.get(name, "") or "")
    except Exception:
        return ""


@st.cache_resource(show_spinner=False)
def get_client(api_key):
    if not GENAI_OK:
        raise RuntimeError("google-genai is not installed. Install requirements.txt first.")
    return genai.Client(api_key=api_key)


def prep_image(raw):
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1024, 1024))
    return img


PROMPT = '''You are a food-recognition and nutrition-estimation assistant. Analyze the food visible in this photo. Identify visible items and estimate portion sizes and nutrition for the portion shown. User hint (may be empty): "{note}".
Return ONLY valid JSON with this schema:
{{"is_food":true,"meal_name":"short descriptive name","confidence":"high","health_score":7,"items":[{{"name":"item","portion":"150 g","calories":200,"protein_g":10,"carbs_g":20,"fat_g":8}}],"total":{{"calories":200,"protein_g":10,"carbs_g":20,"fat_g":8,"fiber_g":4,"sugar_g":3,"sodium_mg":300}},"tips":["short practical tip"]}}
If there is no food, return {{"is_food":false,"meal_name":"","confidence":"low","health_score":5,"items":[],"total":{{}},"tips":[]}}. Values are estimates; do not claim exact measurement.'''


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
        return None


def analyze_food(img, api_key, model, note):
    client = get_client(api_key)
    response = client.models.generate_content(
        model=model,
        contents=[img, PROMPT.format(note=(note or "").replace('"', "'"))],
        config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json"),
    )
    data = parse_json(response.text)
    if not data:
        raise ValueError("The AI response could not be read. Please try again.")
    data.setdefault("is_food", True)
    data.setdefault("meal_name", "Your meal")
    data.setdefault("confidence", "medium")
    data.setdefault("items", [])
    data.setdefault("tips", [])
    total = data.get("total") or {}
    keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg")
    for item in data["items"]:
        for field in ("calories", "protein_g", "carbs_g", "fat_g"):
            item[field] = round(safe_num(item.get(field)), 1)
    total = {key: round(safe_num(total.get(key)), 1) for key in keys}
    if total["calories"] == 0 and data["items"]:
        for field in ("calories", "protein_g", "carbs_g", "fat_g"):
            total[field] = round(sum(safe_num(item.get(field)) for item in data["items"]), 1)
    data["total"] = total
    data["health_score"] = int(min(max(safe_num(data.get("health_score"), 5), 1), 10))
    data["id"] = str(uuid.uuid4())
    return data


def macro_chart(protein, carbs, fat, calories):
    values = [protein * 4, carbs * 4, fat * 9]
    fig = go.Figure(go.Pie(labels=["Protein", "Carbs", "Fat"], values=values if sum(values) else [1, 1, 1], hole=.65,
                           marker=dict(colors=["#6366f1", "#f59e0b", "#ef4444"]), textinfo="percent"))
    fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10), showlegend=True,
                      legend=dict(orientation="h", y=-.08, x=.5, xanchor="center"),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      annotations=[dict(text=f"{calories:.0f}<br>kcal", x=.5, y=.5, showarrow=False)])
    return fig


with st.sidebar:
    st.markdown("## 👤 Your Profile")
    name = st.text_input("Name", placeholder="Your name")
    c1, c2 = st.columns(2)
    age = c1.number_input("Age", min_value=10, max_value=100, value=25)
    gender = c2.selectbox("Gender", ["Male", "Female"])
    height = c1.number_input("Height (cm)", min_value=100.0, max_value=230.0, value=170.0, step=.5)
    weight = c2.number_input("Weight (kg)", min_value=25.0, max_value=250.0, value=70.0, step=.5)
    activity = st.selectbox("Activity level", list(ACTIVITY), index=1)
    goal = st.selectbox("Goal", list(GOALS), index=0)
    st.divider()
    st.markdown("## 🔑 AI Settings")
    secret_key = get_secret("GEMINI_API_KEY")
    if secret_key:
        api_key = secret_key
        st.success("API key loaded from secrets ✅")
    else:
        api_key = st.text_input("Gemini API key", type="password", help="Create a key at https://aistudio.google.com/apikey")
    default_model = get_secret("GEMINI_MODEL") or MODELS[0]
    model_options = MODELS if default_model in MODELS else [default_model] + MODELS
    model = st.selectbox("Vision model", model_options, index=model_options.index(default_model))
    st.caption("Food photos are sent to Google Gemini for analysis. Avoid uploading sensitive images.")

bmi = calc_bmi(weight, height)
category, category_color = bmi_category(bmi)
bmr = calc_bmr(weight, height, age, gender)
tdee = bmr * ACTIVITY[activity]
floor_kcal = 1500 if gender == "Male" else 1200
target = max(round(tdee + GOALS[goal]), floor_kcal)
t_pro, t_carb, t_fat = macro_targets(target, weight, goal)
log_df = pd.DataFrame(st.session_state.log)
eaten = float(log_df["calories"].sum()) if not log_df.empty else 0.0
remaining = target - eaten

greeting = f"Hi {name.strip()} 👋" if name.strip() else "Cal AI"
st.markdown(f'<div class="hero"><h1>{greeting}</h1><p>Snap your meal, estimate calories and macros, track your day, and explore a BMI-based fitness plan.</p></div>', unsafe_allow_html=True)
st.markdown(f'''<div class="kpis">
<div class="kpi g1"><div class="lbl">Eaten today</div><div class="val">{eaten:,.0f}</div><div>kcal</div></div>
<div class="kpi g2"><div class="lbl">Daily target</div><div class="val">{target:,}</div><div>kcal · {goal}</div></div>
<div class="kpi g3"><div class="lbl">{'Remaining' if remaining >= 0 else 'Over target'}</div><div class="val">{abs(remaining):,.0f}</div><div>kcal</div></div>
<div class="kpi g4"><div class="lbl">BMI</div><div class="val">{bmi:.1f}</div><div>{category}</div></div></div>''', unsafe_allow_html=True)

tab_scan, tab_log, tab_fit, tab_about = st.tabs(["📸 Scan Food", "📊 Today's Log", "🏋️ Fitness Plan", "ℹ️ How it works"])

with tab_scan:
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown("### 📷 Capture your meal")
        source = st.radio("Image source", ["📷 Live camera", "🖼️ Upload photo"], horizontal=True, label_visibility="collapsed")
        if source.startswith("📷"):
            pic = st.camera_input("Point your camera at the plate and take a photo")
        else:
            pic = st.file_uploader("Upload a food photo", type=["jpg", "jpeg", "png", "webp"])
        if pic is not None:
            st.image(pic, caption="Selected meal photo", use_container_width=True)
        note = st.text_input("Optional hint", placeholder="e.g. 2 rotis, 1 bowl dal, 200 ml lassi")
        analyze_button = st.button("✨ Analyze Meal", type="primary", disabled=pic is None)
        if analyze_button and pic is not None:
            if not GENAI_OK:
                st.error("google-genai is missing. Install dependencies from requirements.txt.")
            elif not api_key:
                st.warning("Add your Gemini API key in the sidebar or Streamlit secrets.")
            else:
                with st.spinner("🔍 Identifying food and estimating nutrition..."):
                    try:
                        st.session_state.result = analyze_food(prep_image(pic.getvalue()), api_key, model, note)
                    except Exception as exc:
                        message = str(exc)
                        if any(term in message for term in ["API key", "API_KEY", "401", "403"]):
                            st.error("Invalid API key. Check your Gemini key.")
                        elif any(term in message.lower() for term in ["429", "quota", "resource_exhausted"]):
                            st.error("Gemini quota or rate limit reached. Wait a little and try again.")
                        elif "404" in message or "not found" in message.lower():
                            st.error(f"Model {model!r} may not be available for your API key. Try another model.")
                        else:
                            st.error(f"Analysis failed: {message[:300]}")
    with right:
        result = st.session_state.result
        st.markdown("### 🍽️ Results")
        if result is None:
            st.markdown('<div class="card" style="text-align:center;padding:2rem"><div style="font-size:3rem">🥗</div><b>No meal scanned yet</b><p>Take or upload a photo, then tap Analyze Meal.</p></div>', unsafe_allow_html=True)
        elif not result.get("is_food", True):
            st.warning("I couldn't identify food in this photo. Try a clear photo of the whole meal.")
        else:
            total = result["total"]
            score = result["health_score"]
            st.markdown(f"#### {result.get('meal_name') or 'Your meal'}")
            st.caption(f"{str(result.get('confidence', 'medium')).title()} confidence · {len(result.get('items', []))} item(s). Nutrition is an estimate.")
            pct = total["calories"] / target * 100 if target else 0
            score_color = "#22c55e" if score >= 7 else "#f59e0b" if score >= 4 else "#ef4444"
            st.markdown(f'<div class="cal-card"><div>🔥 Total calories</div><div class="cal-big">{total["calories"]:,.0f} <span style="font-size:1rem">kcal</span></div><div>{pct:.0f}% of daily target</div><p style="margin:.5rem 0 0">Health score: <b style="color:{score_color}">{score}/10</b></p></div>', unsafe_allow_html=True)
            st.markdown(f'''<div class="macro-grid">
<div class="macro"><div>🥩</div><b>{total['protein_g']:.0f} g</b><div>Protein</div></div>
<div class="macro"><div>🌾</div><b>{total['carbs_g']:.0f} g</b><div>Carbs</div></div>
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
    st.markdown("### 🏋️ Suggested activities")
    ex_cols = st.columns(2)
    for index, (emoji, exercise, instructions, minutes) in enumerate(EXERCISES[category]):
        ex_cols[index % 2].markdown(f'<div class="card"><b>{emoji} {exercise}</b><br><small>{instructions}</small><br><small>⏱ Suggested duration: {minutes} min</small></div>', unsafe_allow_html=True)
    st.markdown("### 📅 Weekly schedule")
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

st.markdown('<p style="text-align:center;opacity:.6;font-size:.8rem;margin-top:2rem">Made with ❤️ using Streamlit and Google Gemini · Cal AI</p>', unsafe_allow_html=True)
