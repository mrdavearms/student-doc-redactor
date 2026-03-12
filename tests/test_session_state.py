import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'core'))

import importlib
from unittest.mock import patch


class _AttrDict(dict):
    """Dict subclass that supports attribute-style access (like st.session_state)."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(key)


class TestSessionStateInit:
    """Verify session state initialises organisation_names and redact_header_footer."""

    @patch('streamlit.session_state', new_callable=_AttrDict)
    @patch('streamlit.rerun')
    def test_organisation_names_initialised(self, mock_rerun, mock_state):
        import session_state as ss
        importlib.reload(ss)

        ss.init_session_state()
        assert mock_state.get('organisation_names') == ''

    @patch('streamlit.session_state', new_callable=_AttrDict)
    @patch('streamlit.rerun')
    def test_redact_header_footer_initialised(self, mock_rerun, mock_state):
        import session_state as ss
        importlib.reload(ss)

        ss.init_session_state()
        assert mock_state.get('redact_header_footer') is True
