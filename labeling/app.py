"""
Vitiscan Labeling — dashboard Streamlit de revue/labellisation des photos soumises par les
viticulteurs via ui/ (cf. ui/storage.py) et de calcul du drift entre la prédiction du modèle en
prod et le label humain assigné ici.
"""
import logging
import os

import requests
import streamlit as st
from dotenv import load_dotenv

import db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

API_DIAGNO = os.getenv("API_DIAGNO", "http://localhost:4000").replace('"', '')
PAGE_SIZE = int(os.getenv("LABELING_PAGE_SIZE", "20"))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0'
}


@st.cache_data(ttl=300)
def get_diseases() -> dict:
    """Maladies connues du modèle en prod (mêmes labels que la prédiction), pour peupler le
    dropdown de labellisation humaine - même pattern que ui/app.py::get_diseases, sans MOCK (outil
    interne toujours branché sur une vraie API)."""
    try:
        response = requests.get(f"{API_DIAGNO}/diseases", headers=HEADERS, timeout=60)
        response.raise_for_status()
        return dict(response.json()["diseases"])
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur appel {API_DIAGNO}/diseases : {e}")
        return {}


def render_drift_banner(conn, model_version_filter):
    metrics = db.compute_drift_metrics(conn, model_version=model_version_filter)
    st.subheader("Drift : accord prédiction / label humain")
    if metrics["n_labeled"] == 0:
        st.info("Aucune photo labellisée pour l'instant.")
        return

    col1, col2 = st.columns(2)
    col1.metric("Photos labellisées", metrics["n_labeled"])
    col2.metric("Taux d'accord global", f"{metrics['global_agreement'] * 100:.1f}%")

    if len(metrics["by_model_version"]) > 1:
        st.caption("Taux d'accord par version de modèle :")
        chart_data = {
            row["model_version"]: row["agreement"]
            for row in metrics["by_model_version"] if row["agreement"] is not None
        }
        if chart_data:
            st.bar_chart(chart_data)


def render_filters(conn) -> dict:
    st.sidebar.header("Filtres")
    model_versions = db.list_distinct(conn, "model_version")
    predicted_labels = db.list_distinct(conn, "predicted_label")

    model_version = st.sidebar.selectbox("Version du modèle", options=["Toutes"] + model_versions)
    predicted_label = st.sidebar.selectbox("Maladie prédite", options=["Toutes"] + predicted_labels)
    status = st.sidebar.selectbox(
        "Statut",
        options=["all", "incoming", "accepted", "rejected"],
        format_func=lambda x: {
            "all": "Toutes", "incoming": "Incoming", "accepted": "Acceptées", "rejected": "Rejetées",
        }[x],
    )
    only_duplicates = st.sidebar.checkbox("Doublons uniquement (même photo envoyée plusieurs fois)")

    st.sidebar.divider()
    # Pas d'authentification dans ce projet : champ libre, non fiable en intégrité (cf.
    # labeling/README.md).
    st.session_state["labeled_by"] = st.sidebar.text_input(
        "Votre nom/pseudo (enregistré avec chaque décision)",
        value=st.session_state.get("labeled_by", ""),
    )

    return {
        "model_version": None if model_version == "Toutes" else model_version,
        "predicted_label": None if predicted_label == "Toutes" else predicted_label,
        "status": None if status == "all" else status,
        "only_duplicates": only_duplicates,
    }


def render_photo_card(conn, photo: dict, disease_translation: dict) -> None:
    with st.container(border=True):
        cols = st.columns([1, 2])

        with cols[0]:
            try:
                st.image(db.presigned_url(photo["s3_key"]), width=200)
            except Exception:
                logger.exception(f"Aperçu S3 indisponible pour {photo['s3_key']}")
                st.warning("Aperçu indisponible")

            if photo["duplicate_count"] > 1:
                st.warning(f"Doublon détecté ({photo['duplicate_count']}x)")

        with cols[1]:
            predicted = photo["predicted_label"]
            st.markdown(
                f"**Prédiction** : {disease_translation.get(predicted, predicted)} "
                f"({photo['confidence'] * 100:.1f}%)"
            )
            st.caption(f"Modèle : {photo['model_version']} — soumis le {photo['submitted_at']}")
            if photo["gps_lat"] is not None and photo["gps_lon"] is not None:
                st.caption(f"GPS : {photo['gps_lat']:.5f}, {photo['gps_lon']:.5f}")

            status = photo["status"]
            if status == "incoming":
                options = list(disease_translation.keys()) or [predicted]
                default_index = options.index(predicted) if predicted in options else 0

                selected = st.selectbox(
                    "Label humain",
                    options=options,
                    format_func=lambda x: disease_translation.get(x, x),
                    index=default_index,
                    key=f"label_select_{photo['id']}",
                )
                btn_accept, btn_reject = st.columns(2)
                labeled_by = st.session_state.get("labeled_by") or "inconnu"
                if btn_accept.button("✅ Accepter", key=f"accept_{photo['id']}", type="primary"):
                    try:
                        db.accept_photo(conn, photo["id"], selected, labeled_by)
                        st.success("Photo acceptée dans le dataset.")
                        st.rerun()
                    except Exception:
                        logger.exception(f"Échec accept_photo pour la photo {photo['id']}")
                        st.error("Échec de l'acceptation (S3/Neon) - réessayer.")
                if btn_reject.button("❌ Rejeter", key=f"reject_{photo['id']}"):
                    try:
                        db.reject_photo(conn, photo["id"], labeled_by, selected)
                        st.success("Photo rejetée.")
                        st.rerun()
                    except Exception:
                        logger.exception(f"Échec reject_photo pour la photo {photo['id']}")
                        st.error("Échec du rejet (S3/Neon) - réessayer.")
            else:
                badge = "✅ Acceptée" if status == "accepted" else "❌ Rejetée"
                st.markdown(f"**{badge}**")
                if photo["human_label"]:
                    st.caption(
                        f"Label : {disease_translation.get(photo['human_label'], photo['human_label'])} "
                        f"(par {photo['labeled_by'] or '?'} le {photo['labeled_at']})"
                    )


def main():
    st.set_page_config(page_title="Vitiscan Labeling", page_icon="🏷️", layout="wide")
    st.title("Vitiscan Labeling — revue et labellisation des photos")

    disease_translation = get_diseases()

    with db.db_client() as conn:
        db.ensure_schema(conn)

        filters = render_filters(conn)
        render_drift_banner(conn, filters["model_version"])
        st.divider()

        filters_signature = tuple(filters.values())
        if st.session_state.get("labeling_filters_signature") != filters_signature:
            st.session_state["labeling_page"] = 1
            st.session_state["labeling_filters_signature"] = filters_signature
        if "labeling_page" not in st.session_state:
            st.session_state["labeling_page"] = 1

        rows, total = db.list_photos(
            conn,
            model_version=filters["model_version"],
            predicted_label=filters["predicted_label"],
            status=filters["status"],
            only_duplicates=filters["only_duplicates"],
            page=st.session_state["labeling_page"],
            page_size=PAGE_SIZE,
        )

        st.write(f"**{total}** photo(s)")

        for photo in rows:
            render_photo_card(conn, photo, disease_translation)

        n_pages = max(1, -(-total // PAGE_SIZE))
        col_prev, col_page, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ Précédent", disabled=st.session_state["labeling_page"] <= 1):
                st.session_state["labeling_page"] -= 1
                st.rerun()
        with col_page:
            st.write(f"Page {st.session_state['labeling_page']} / {n_pages}")
        with col_next:
            if st.button("Suivant ▶", disabled=st.session_state["labeling_page"] >= n_pages):
                st.session_state["labeling_page"] += 1
                st.rerun()


if __name__ == "__main__":
    main()
