# Router Chat

This sample routes requests between:

- the CPU endpoint created by `apps/oci-inference-cloud`
- OpenAI using a participant-provided API key

## Run

```bash
cd examples/router-chat
npm install
CPU_ENDPOINT_URL=http://127.0.0.1:8090/api/experiments/1/endpoint/v1 \
OPENAI_API_KEY=replace-with-your-key \
OPENAI_MODEL=gpt-4.1-mini \
PORT=3002 \
npm run dev
```

Open `http://127.0.0.1:3002`.

## Routing Rule

In auto mode, short prompts with modest output budgets go to the CPU endpoint. Longer prompts or high output budgets go to OpenAI. The UI shows the selected provider and route reason for every request.
