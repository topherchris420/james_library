import os

# Set env vars BEFORE any other imports so _init_rag() is never triggered
# by the module-level tools.py init block or the RLM setup_code execution.
os.environ["RLM_REQUIRE_WEB"] = "0"
os.environ["RAIN_SKIP_RAG"] = "1"

from unittest.mock import MagicMock, patch

from rain_lab_meeting import ResearchCouncil
from tools import get_setup_code


class TestIntegrationFlow:
    @patch('rain_lab_meeting.RLM.completion')
    def test_mocked_council_meeting(self, mock_completion):
        # Mock LLM response to simulate calling the newly injected read_paper tool
        mock_completion.return_value = MagicMock(response='''
```python
content = read_paper("coherence")
```
Hey team, so today we're looking into 'Coherence Depth'. I found relevant excerpts in the library. What are your thoughts?
''')
        # Bypass DuckDuckGo requirement since we are just unit testing the flow
        os.environ["RLM_REQUIRE_WEB"] = "0"
        council = ResearchCouncil()
        assert len(council.team) == 4
        
        # Test that the setup code injects correctly
        setup = get_setup_code()
        assert "def read_paper(keyword):" in setup
        assert "def list_papers():" in setup
        assert "def search_library(query):" in setup
        
        # Manually invoke the RLM to verify it doesn't crash given the setup code
        # We replace the actual generate with our mock
        prompt = council.build_prompt(council.team[0], "Coherence Depth", [], 0)
        response = council.rlm.completion(prompt)
        
        assert "read_paper" in response.response
        assert "Hey team" in response.response
