"""Run against an explicitly started isolated test server on localhost."""
import concurrent.futures
import json
import urllib.request
import urllib.error

BASE="http://127.0.0.1:39183"
SPEC={"targets":[{"layer":1,"site":"block_output"},{"layer":2,"site":"ffn_output"}],
      "tokens":{"prompt":"all","generated":"processed"},"encoding":"base64"}


def post(path,payload):
    req=urllib.request.Request(BASE+path,json.dumps(payload).encode(),{"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=60) as response:
        if payload.get("stream"):
            return [json.loads(line[6:]) for line in response.read().decode().splitlines()
                    if line.startswith("data: ") and line!="data: [DONE]"]
        return json.load(response)


def check(chunks):
    seen=set()
    assert chunks
    for chunk in chunks:
        for pos in chunk["positions"]:
            key=chunk["layer"],chunk["site"],pos
            assert key not in seen, key
            seen.add(key)
    assert {c["layer"] for c in chunks}=={1,2}


def main():
    native={"input_ids":[3,4,5,6],"sampling_params":{"max_new_tokens":4,"temperature":0,"ignore_eos":True},
            "activation_capture":SPEC,"return_logprob":True}
    out=post("/generate",native)
    check(out["meta_info"]["activations"]["chunks"])
    assert out["meta_info"]["output_token_logprobs"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outputs=list(pool.map(lambda _:post("/generate",native),range(8)))
    for out in outputs: check(out["meta_info"]["activations"]["chunks"])
    for endpoint in ("completions","chat/completions"):
        payload={"model":"default","max_tokens":4,"temperature":0,"ignore_eos":True,"activation_capture":SPEC}
        if endpoint=="completions":payload["prompt"]="t3 t4 t5 t6"
        else:payload["messages"]=[{"role":"user","content":"t3 t4 t5 t6"}]
        out=post("/v1/"+endpoint,payload)
        check(out["choices"][0]["activations"]["chunks"])
        payload["stream"]=True
        chunks=[]
        for event in post("/v1/"+endpoint,payload):
            for choice in event.get("choices",[]):
                activation=choice.get("activations") or choice.get("delta",{}).get("activations")
                if activation:chunks.extend(activation["chunks"])
        check(chunks)
    try:
        post("/generate",{**native,"activation_capture":{**SPEC,"targets":[{"layer":99,"site":"block_output"}]}})
        raise AssertionError("invalid layer accepted")
    except urllib.error.HTTPError as error:
        assert error.code==400,error.code
    print("HTTP native + 8 concurrent requests + OpenAI completion/chat + SSE + validation: PASS")


if __name__=="__main__":main()
