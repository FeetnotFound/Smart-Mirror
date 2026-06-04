import os
import json
import warnings
from pathlib import Path
from typing import Tuple, Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, logging
from peft import PeftModel

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
warnings.filterwarnings("ignore", message=".*generation flags are not valid.*")
logging.set_verbosity_error()

from config import LOCAL_ROUTER_PATH, BASE_MODEL_PATH, ROUTER, RESET, SYSTEM, ts

# ── All functions the router is allowed to dispatch ──────────────────────────
VALID_FUNCTIONS: frozenset[str] = frozenset({
    "thinking", "nonthinking",
    "control_light", "control_calendar_event", "create_calendar_event",
    "set_alarm", "set_timer", "web_search", "get_system_info", "add_task",
})

SYSTEM_PROMPT = """\
You are a function calling AI. You have access to the following functions:

- set_timer(duration, label)
- set_alarm(time, label)
- control_light(action, device_name, brightness, color)
- control_user_interface(action, module, location, size)
- create_calendar_event(title, date, time, duration)
- add_task(text, priority)
- web_search(query)
- get_system_info()
- thinking(prompt)
- nonthinking(prompt)

Respond with the appropriate function call in this format:
<function_call>{"name": "function_name", "arguments": {"arg1": "value1"}}</function_call>"""


def _check_model_available(model_path: str) -> str:
    """Return model_path if the model files exist, otherwise empty string."""
    path = Path(model_path)
    exists = (path / "adapter_model.safetensors").exists() or \
             (path / "model.safetensors").exists()
    if exists:
        print(f"{ts()}{SYSTEM}[System] Model found: {model_path}{RESET}")
        return model_path
    print(f"{ts()}{SYSTEM}[System] Model NOT found: {model_path}{RESET}")
    return ""


class FunctionRouter:
    """Lightweight LLM-based function router using a LoRA fine-tuned model."""

    def __init__(self, model_path: str = LOCAL_ROUTER_PATH,
                 base_model_path: str = BASE_MODEL_PATH) -> None:

        model_path      = _check_model_available(model_path)
        base_model_path = _check_model_available(base_model_path)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        # BUG FIX: was torch.float23 (doesn't exist) → torch.float32
        dtype  = torch.bfloat16 if device == "cuda" else torch.float32

        print(f"{ts()}{SYSTEM}[System] Loading router on {device.upper()}{RESET}")

        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        # BUG FIX: kwarg was `dtype=` → correct kwarg is `torch_dtype=`
        base = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            torch_dtype=dtype,
            device_map=device,
        )
        self.model = PeftModel.from_pretrained(base, model_path)
        self.model.eval()

    # ── Parsing ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(raw: str) -> Tuple[str, dict[str, Any]]:
        """Extract and validate a function call from the model's raw output."""
        try:
            inner  = raw.split("<function_call>")[-1].split("</function_call>")[0]
            data   = json.loads(inner)
            name   = data["name"]
            args   = data["arguments"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"Malformed router output: {exc}\nRaw: {raw!r}") from exc

        # Validate against the known function whitelist
        if name not in VALID_FUNCTIONS:
            raise ValueError(f"Router returned unknown function: {name!r}")

        return name, args

    # ── Inference ─────────────────────────────────────────────────────────────

    @torch.inference_mode()
    def route(self, user_input: str) -> Tuple[str, dict[str, Any]]:
        """Route a user utterance to the appropriate function + arguments."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_input},
        ]
        prompt = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)

        outputs = self.model.generate(
            **inputs,
            max_new_tokens=40,   # function call JSON is ≤35 tokens; 100 was wasteful
            do_sample=False,
            use_cache=True,
            pad_token_id=self.tokenizer.pad_token_id,
        )

        # Decode only the newly generated tokens
        new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
        response   = self.tokenizer.decode(new_tokens, skip_special_tokens=False)

        return self._parse_response(response)