import os
import frontmatter
from typing import List, Dict, Any, Optional


class RunbookService:
    def __init__(self, runbooks_dir: str):
        self.runbooks_dir = runbooks_dir

    def list_runbooks(self) -> List[Dict[str, Any]]:
        runbooks = []
        if not os.path.exists(self.runbooks_dir):
            return []

        for filename in os.listdir(self.runbooks_dir):
            if not filename.endswith(".md"):
                continue
            path = os.path.join(self.runbooks_dir, filename)
            try:
                post = frontmatter.load(path)
                name = post.metadata.get("name")
                trigger = post.metadata.get("trigger")
                if not name or not trigger:
                    continue
                runbook_id = filename[:-3]  # strip .md
                runbooks.append({
                    "id": runbook_id,
                    "name": name,
                    "trigger": trigger,
                    "body": post.content,
                })
            except Exception as e:
                print(f"Error loading runbook {filename}: {e}")
        return runbooks

    def get_runbook(self, runbook_id: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.runbooks_dir, f"{runbook_id}.md")
        if not os.path.exists(path):
            return None
        try:
            post = frontmatter.load(path)
            return {
                "id": runbook_id,
                "name": post.metadata.get("name", runbook_id),
                "trigger": post.metadata.get("trigger", ""),
                "body": post.content,
            }
        except Exception as e:
            print(f"Error reading runbook {runbook_id}: {e}")
            return None

    def save_runbook(self, runbook_id: str, content: str) -> bool:
        try:
            post = frontmatter.loads(content)
            if not post.metadata.get("name") or not post.metadata.get("trigger"):
                return False
            os.makedirs(self.runbooks_dir, exist_ok=True)
            filename = f"{runbook_id}.md"
            path = os.path.join(self.runbooks_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"Error saving runbook: {e}")
            return False


# Global instance
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_app_dir = os.path.dirname(current_dir)
runbooks_path = os.path.join(backend_app_dir, "runbooks")

runbook_service = RunbookService(runbooks_path)


def match_runbook_logic(query: str) -> dict:
    from app.services.ai_service import ai_service
    import json
    import re

    runbooks = runbook_service.list_runbooks()
    if not runbooks:
        return {"matched_runbook_id": None, "confidence": "none", "reasoning": "No runbooks"}

    candidates = [
        {"id": r["id"], "name": r["name"], "trigger": r["trigger"]}
        for r in runbooks
    ]

    system_prompt = f"""Given this user query: '{query}'
And these runbooks: {json.dumps(candidates)}

Return a JSON object formatted exactly like this:
{{
  "matched_runbook_id": "string if match else null",
  "confidence": "high|medium|low|none",
  "reasoning": "string",
  "suggested_first_tool": "string or null"
}}

Return null for matched_runbook_id if no runbook fits.
Be conservative — only match if the trigger clearly fits.
"""

    try:
        client = ai_service._get_client()
        provider = ai_service._get_setting("ai_provider")
        model = ai_service._get_setting("ai_model") or "gpt-3.5-turbo"

        if provider == "GEMINI":
            resp = client.generate_content(system_prompt)
            text = resp.text
        else:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": system_prompt}],
                temperature=0
            )
            text = resp.choices[0].message.content

        clean_text = re.sub(r"```json|```", "", text).strip()
        match = re.search(r"\{.*\}", clean_text, re.DOTALL)
        if match:
            clean_text = match.group(0)

        parsed = json.loads(clean_text)

        if parsed.get("matched_runbook_id"):
            rb = runbook_service.get_runbook(parsed["matched_runbook_id"])
            if rb:
                parsed["runbook_name"] = rb["name"]
                parsed["runbook_body"] = rb["body"]

        return parsed

    except Exception as e:
        return {"matched_runbook_id": None, "confidence": "none", "reasoning": str(e), "suggested_first_tool": None}


runbook_service.match_runbook_logic = match_runbook_logic
