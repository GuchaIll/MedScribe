import time

from .registry import get_llm_client


class LLMClient:
    def __init__(self):
        packed = get_llm_client()
        self.model_type = packed["type"]
        self.provider = packed.get("provider")
        self.model = packed["model"]
        self.model_name = packed.get("model_name")
        self.tokenizer = packed.get("tokenizer", None)

    def generate_response(self, prompt: str, max_tokens: int | None = None) -> str:
        if self.model_type == "local":
            _max = max_tokens or 150
            start_time = time.time()

            tokenize_start = time.time()
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            tokenize_time = time.time() - tokenize_start

            generate_start = time.time()
            outputs = self.model.generate(**inputs, max_new_tokens=_max)
            generate_time = time.time() - generate_start

            decode_start = time.time()
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            decode_time = time.time() - decode_start

            total_time = time.time() - start_time

            print("######################################################")
            print("LLM Profiling:")
            print(f"  Tokenization: {tokenize_time:.3f}s")
            print(f"  Generation: {generate_time:.3f}s")
            print(f"  Decoding: {decode_time:.3f}s")
            print(f"  Total: {total_time:.3f}s")
            print(f"  Tokens/sec: {_max / generate_time:.2f}")
            print(f"LLM response: {response}")
            print("######################################################")

            return response

        if self.model_type == "api":
            if self.provider in ["groq", "openai", "openrouter"]:
                kwargs: dict = {
                    "messages": [{"role": "user", "content": prompt}],
                    "model": self.model_name,
                }
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                chat_completion = self.model.chat.completions.create(**kwargs)
                return chat_completion.choices[0].message.content

            if self.provider == "anthropic":
                message = self.model.messages.create(
                    model=self.model_name,
                    max_tokens=max_tokens or 600,
                    messages=[{"role": "user", "content": prompt}],
                )
                return message.content[0].text

            if self.provider == "google":
                response = self.model.generate_content(prompt)
                return response.text

            raise ValueError(f"Unsupported API provider: {self.provider}")

        raise ValueError(f"Unsupported model type: {self.model_type}")
