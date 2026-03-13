import time
import os
from groq import Groq
from .registry import get_llm_client


class LLMClient:
    def __init__(self):
       packed = get_llm_client()
       self.model_type = packed["type"]
       self.model = packed["model"]
       self.tokenizer = packed.get("tokenizer", None)
    
    
    def generate_response(self, prompt: str) -> str:
        if self.model_type == "local":
            start_time = time.time()
            
            # Tokenization
            tokenize_start = time.time()
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            tokenize_time = time.time() - tokenize_start
            
            # Generation
            generate_start = time.time()
            outputs = self.model.generate(**inputs, max_new_tokens=150)
            generate_time = time.time() - generate_start
            
            # Decoding
            decode_start = time.time()
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            decode_time = time.time() - decode_start
            
            total_time = time.time() - start_time
            
            print("######################################################")
            print(f"LLM Profiling:")
            print(f"  Tokenization: {tokenize_time:.3f}s")
            print(f"  Generation: {generate_time:.3f}s")
            print(f"  Decoding: {decode_time:.3f}s")
            print(f"  Total: {total_time:.3f}s")
            print(f"  Tokens/sec: {150 / generate_time:.2f}")
            print(f"LLM response: {response}")
            print("######################################################")
            
            return response
            
        elif self.model_type == "api":
            # Use Groq API for fast cloud inference
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
            
            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model="llama-3.3-70b-versatile",
            )

            return chat_completion.choices[0].message.content

        else:
            raise ValueError(f"Unsupported model type: {self.model_type}")
        
    
        
    
    

