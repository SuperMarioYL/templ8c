"""Check local Jinja templates against a bundled spec, including one deliberate change."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from templ8c.checker import Checker
from templ8c.template_loader import TemplateLoader
from templ8c.reference.specs import get_spec
model="qwen3.8"
spec=get_spec(model)
with TemporaryDirectory(prefix="templ8c-demo-") as folder:
    path=Path(folder)/"tokenizer_config.json"
    path.write_text(json.dumps({"chat_template":spec.template}))
    source=TemplateLoader().load_from_tokenizer_config(path)
    for label,template in [("bundled example",source),("wrapper removed",source.replace(spec.tool_call_wrapper,""))]:
        result=Checker().check_source(model,template)
        print(json.dumps({"input":label,"passed":result.passed,"checks":len(result.diffs),"failed_fields":[d.field for d in result.diffs if d.status=="FAIL"]}))
print("Scope: repository-authored reference templates; no upstream model release or inference server tested.")
