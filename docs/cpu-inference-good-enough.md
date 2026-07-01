# CPU Inference Is Enough When...

GPU inference is not the only useful deployment pattern. For a hackathon or prototype, CPU inference can be good enough when the workload is small, predictable, or latency-tolerant.

## Good CPU Fits

- Short prompts with short or medium answers.
- Internal tools where a few users interact at a time.
- Agent steps that classify, rewrite, summarize, or extract fields.
- Demos where cost, availability, and simplicity matter more than peak throughput.
- Fallback paths where the model can be smaller or quantized.

## When To Escalate To A Hosted Or GPU Model

- Very long prompts or large context windows.
- High concurrency with strict latency targets.
- Long-form generation where decode throughput dominates.
- Tasks that require a stronger model than the local CPU model.
- User-facing products with unpredictable traffic spikes.

## What To Measure

- Time to first token: how long users wait before seeing output.
- End-to-end latency: full request duration.
- Throughput: requests/sec and output chars/sec.
- Approximate tokens/sec: output chars/sec divided by 4.
- Route split: how many requests stayed on CPU versus escalated.

## Hackathon Lesson

The goal is not to prove CPU is always better. The goal is to show that many requests do not need the biggest model or a GPU path. A router can keep simple requests local and reserve external LLM calls for prompts that actually need them.
