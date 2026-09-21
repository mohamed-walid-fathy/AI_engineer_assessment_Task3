import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from data_layer import load_clean, data_reference_date
from intent import route
from tools import TOOLS
from narration import narrate

st.set_page_config(page_title="Ops Intelligence Assistant", layout="wide")

DATA_PATH = os.environ.get(
    "OPS_DATA_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "operations_data_anonymized.xlsx"),
)
# Fallbacks: repo may sit next to the dataset or under data/
_CANDIDATES = [
    DATA_PATH,
    os.path.join(os.getcwd(), "operations_data_anonymized.xlsx"),
    os.path.join(os.path.dirname(os.getcwd()), "operations_data_anonymized.xlsx"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                 "operations_data_anonymized.xlsx"),
]


def _resolve(path_list):
    for p in path_list:
        if p and os.path.isfile(os.path.normpath(p)):
            return os.path.normpath(p)
    return os.path.normpath(path_list[0])


RESOLVED = _resolve(_CANDIDATES)


@st.cache_data(show_spinner="Loading and cleaning data...")
def get_data(path):
    return load_clean(path)


st.title("Operations Intelligence Assistant")
st.caption("Ask about delivery performance, complaints, or anomalies. "
           "Numbers come from fixed analytics over the loaded extract — never from the language model.")

try:
    df = get_data(RESOLVED)
except FileNotFoundError:
    st.error(f"Could not find data file. Tried: {RESOLVED}. Set OPS_DATA_PATH env var.")
    st.stop()

ref = data_reference_date(df)
st.info(f"Answering relative to latest data date **{ref.date()}**. "
        "'Last month' = most recent full calendar month before that date.")

examples = [
    "Which branch got worse at delivery last month, and why?",
    "Are complaints about late orders coming from specific areas, times, or drivers?",
    "Is there anything in this data I should be worried about?",
    "Who is the worst driver?",
    "Show me the top 5 worst drivers.",
]
cols = st.columns(len(examples))
clicked = None
for c, ex in zip(cols, examples):
    if c.button(ex, use_container_width=True):
        clicked = ex

question = st.text_input("Type your question:", value=clicked or "")
ask = st.button("Ask", type="primary")

if ask and question or (question and clicked):
    tool_name, kwargs, method = route(question)

    if tool_name is None:
        st.markdown("### Answer")
        st.warning(kwargs["refusal"])
        st.stop()

    result = TOOLS[tool_name](df, **kwargs)
    try:
        text, narr_method = narrate(tool_name, result, use_gemini=True)
    except Exception:
        from narration import template_narration as _t
        text, narr_method = _t(tool_name, result), "template"

    st.markdown("### Answer")
    st.write(text)

    # The narration already closes with one plain-language data note.
    # Raw technical caveats stay out of the COO-facing answer (evidence JSON
    # below remains fully inspectable).
    from narration import data_note as _data_note
    st.markdown("**Data note:**")
    st.markdown(_data_note(tool_name, result))

    with st.expander("Evidence / supporting metrics"):
        st.json(result["answer_data"])

    with st.expander("Technical details"):
        st.write(f"Intent method: `{method}` · narration: `{narr_method}` · tool: `{tool_name}`")
        st.write(f"Args: `{kwargs}` · rows used: `{result['n_rows']:,}`")
