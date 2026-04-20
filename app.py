import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime, date, time
import pytz
from shadow_engine import get_bars_sunlight_status, CITIES

st.set_page_config(page_title="Terrasses au sun maggle", layout="wide")

st.title("☀️🍻 Terrasses au sun maggle 🍻☀️")
st.caption("Trouve tes 🍻 terrasses 🍻")

city = st.sidebar.selectbox("Ville", list(CITIES.keys()), index=0)
city_info = CITIES[city]
center_lat, center_lon = city_info["center"]
default_radius = city_info["radius"]
slug = city_info["slug"]

with st.sidebar:
    st.header("Paramètres")

    use_now = st.checkbox("Utiliser l'heure actuelle", value=True)

    tz = pytz.timezone("Europe/Paris")
    if use_now:
        dt = datetime.now(tz)
        st.info(f"🕐 {dt.strftime('%d/%m/%Y %H:%M')}")
    else:
        d = st.date_input("Date", value=date.today())
        h = st.slider("Heure", 6, 22, 14)
        m = st.slider("Minute", 0, 59, 0)
        dt = tz.localize(datetime.combine(d, time(h, m)))

    radius = st.slider("Rayon (m)", 300, 2000, default_radius, step=100)

    run = st.button("🔍 Analyser", type="primary", use_container_width=True)

if "last_result" not in st.session_state:
    st.session_state.last_result = None

if run:
    with st.spinner(f"Analyse de {city}..."):
        try:
            bars_df, sun_info = get_bars_sunlight_status(
                center_lat, center_lon, radius, dt, slug=slug
            )
            st.session_state.last_result = (bars_df, sun_info, city, dt)
        except Exception as e:
            st.error(f"Erreur : {e}")
            st.stop()

if st.session_state.last_result:
    bars_df, sun_info, city_name, dt_used = st.session_state.last_result

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bars trouvés", len(bars_df))
    c2.metric("Au soleil ☀️", int(bars_df["sunlit"].sum()))
    c3.metric("Élévation soleil", f"{sun_info['elevation']:.1f}°")
    c4.metric("Azimut soleil", f"{sun_info['azimuth']:.1f}°")

    if sun_info["elevation"] <= 0:
        st.warning("🌙 Le soleil est sous l'horizon — tous les bars sont à l'ombre.")

    m = folium.Map(location=[center_lat, center_lon], zoom_start=15, tiles="CartoDB positron")
    folium.Circle(
        location=[center_lat, center_lon],
        radius=radius,
        color="blue", fill=False, weight=1, opacity=0.3,
    ).add_to(m)

    for _, row in bars_df.iterrows():
        color = "orange" if row["sunlit"] else "gray"
        icon = "☀️" if row["sunlit"] else "🌑"
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.8,
            popup=f"{icon} {row['name'] or '(sans nom)'} — {row['amenity']}",
        ).add_to(m)

    st_folium(m, width=None, height=600, returned_objects=[])

    with st.expander("📋 Liste des bars"):
        st.dataframe(
            bars_df.sort_values("sunlit", ascending=False).reset_index(drop=True),
            use_container_width=True,
        )
else:
    st.info("👈 Choisis une ville et clique sur **Analyser** dans la sidebar.")
