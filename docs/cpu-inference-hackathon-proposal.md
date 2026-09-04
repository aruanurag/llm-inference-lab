# CPU Inference Hackathon Proposal

## Executive Summary

Generative AI adoption is creating a new infrastructure question for customers: which requests really need the largest model or a specialized accelerator path, and which requests can be served well enough by smaller models running on CPUs?

This proposal outlines a customer-facing hackathon built around that question. Participants deploy a small model on OCI CPU compute, benchmark it, expose an OpenAI-compatible endpoint, and build sample applications that route requests between CPU inference and a larger external model. The output is not a theoretical claim that CPU replaces GPU. The output is measured evidence showing where CPU inference is good enough, where routing helps, and how much traffic can avoid the most expensive inference path.

The repository supports this event with a local **OCI Inference Cloud** app that abstracts away OCI setup. It lets participants select an OCI profile, provision compute, deploy `llama.cpp`, run benchmarks, start an endpoint, and use sample apps that track routing analytics.

## Proposed Event

**Working title:** CPU Inference Routing Hackathon

**Core promise:** Build a GenAI application that uses CPU inference first, routes only harder requests to a larger model, and measures the split.

**Participant outcome:** By the end of the hackathon, each team has:

- a CPU-hosted inference endpoint running on OCI compute
- benchmark results for the deployed model and shape
- a working application that calls the CPU endpoint directly or through a router
- analytics showing CPU-handled requests versus external-model requests
- a short explanation of which use cases fit CPU inference and which need escalation

**Organizer outcome:** We get customer-visible proof points around CPU inference, model routing, cost-aware AI architecture, and practical GenAI infrastructure design on OCI compute.

## Future Press Release Draft

**Oracle hosts CPU Inference Routing Hackathon to help developers reduce GenAI inference cost and complexity**

Developers and enterprise teams joined a hands-on hackathon focused on a practical GenAI architecture pattern: run smaller, task-appropriate models on CPU infrastructure, and route only the requests that need larger models to external or specialized inference endpoints.

During the event, participants used a local OCI Inference Cloud workbench to provision OCI compute, deploy an OpenAI-compatible CPU inference endpoint, benchmark performance, and build applications that made transparent routing decisions. Instead of treating every prompt as a request for the largest available model, teams measured which workloads were handled successfully on CPU and which required escalation.

The hackathon helped participants understand that CPU inference can be a first-class part of a GenAI adoption journey. For workloads such as classification, extraction, summarization, rewriting, short answers, workflow steps, and internal tools, smaller CPU-hosted models can often provide enough quality while preserving flexibility and cost control.

The event produced repeatable benchmarks, route-split analytics, working sample apps, and customer-specific lessons about right-sizing inference.

## Why This Matters

Many GenAI prototypes start by sending every request to the strongest available hosted model. That is simple, but it can become expensive and operationally blunt as usage grows.

Customers need a more nuanced pattern:

- Use CPU inference for simple, frequent, or latency-tolerant tasks.
- Use routing logic to escalate complex requests.
- Measure the route split instead of guessing.
- Reserve larger models for the requests that actually need them.

This is aligned with a CPU-focused infrastructure story. It positions CPUs not as a fallback, but as a useful inference tier in a broader AI architecture.

## What The Repository Enables

The repo provides three layers for the hackathon.

### 1. OCI Inference Cloud App

The app reduces the OCI learning curve:

- selects local OCI CLI profiles
- lists compartments, shapes, VCNs, subnets, and images
- provisions OCI compute instances
- generates local SSH keys
- deploys `llama.cpp`
- downloads a selected GGUF model
- starts a private `llama-server`
- exposes a local OpenAI-compatible proxy endpoint
- runs benchmark presets
- exports experiment results

The app keeps generated keys, logs, prompts, benchmarks, and local state outside the repo.

### 2. Benchmarking Workflow

Participants can compare:

- different model sizes
- quantization levels
- OCI shapes
- OCPU and memory settings
- concurrency levels
- prompt lengths
- output lengths
- llama.cpp deployment settings

Core metrics:

- time to first token
- end-to-end latency
- approximate inter-token latency
- requests/sec
- output chars/sec
- approximate output tokens/sec
- route split between CPU and external model

### 3. Sample Applications

The sample apps demonstrate two adoption paths:

- **Direct CPU chat:** calls the generated CPU endpoint directly and shows latency and throughput analytics.
- **Router chat:** routes simple prompts to CPU inference and more complex prompts to a larger OpenAI model, then shows how many requests went to each provider.

These examples give participants a fast starting point while leaving room for custom apps.

## Hackathon Flow

### Phase 1: Setup

Participants install prerequisites, configure OCI CLI, and start the local workbench.

### Phase 2: Provision

Participants create an experiment, choose an OCI shape, and provision compute through the app.

### Phase 3: Deploy

Participants select a model, deploy `llama.cpp`, and start an OpenAI-compatible CPU endpoint.

### Phase 4: Benchmark

Participants run benchmark presets and record latency, throughput, and concurrency behavior.

### Phase 5: Build

Participants build or modify an app that uses CPU inference directly or routes between CPU inference and an external model.

### Phase 6: Analyze

Participants present:

- what they built
- which prompts stayed on CPU
- which prompts escalated
- what route split they observed
- where CPU inference was good enough
- where larger models were still needed

## Suggested Tracks

### Track A: CPU-First App

Build an app that uses only the CPU endpoint. Good fits include summarization helpers, structured extraction, internal Q&A, prompt rewriting, classifiers, and agent utility steps.

### Track B: Cost-Aware Router

Build an app that tries CPU first or uses rule-based routing before calling a larger external model.

### Track C: Benchmark Research

Compare models, shapes, OCPU counts, memory sizes, and concurrency settings. Produce a clear recommendation for one workload.

### Track D: Enterprise Workflow

Pick a realistic business workflow and identify which AI steps can run on CPU and which require escalation.

## Success Metrics

Event success should be measured by learning and repeatable evidence, not only by demos.

Suggested metrics:

- number of teams that successfully deploy a CPU endpoint
- number of apps built on the endpoint
- number of benchmark runs collected
- average and best route split by app category
- percentage of requests handled by CPU in router apps
- latency and throughput ranges by model and shape
- number of customer use cases identified as CPU-suitable
- participant feedback on whether the app reduced OCI onboarding friction

## Leadership Ask

Approve a pilot hackathon with a small customer or partner group.

Requested support:

- limited OCI credits or pre-approved compute budget
- access to a small set of OCI CPU shapes for participants
- one or two solution architects for support
- event landing page or registration support
- permission to publish sanitized benchmark learnings after the pilot
- agreement on follow-up customer conversations based on hackathon outcomes

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Participants expect CPU to beat GPU for every workload | Set the framing clearly: CPU is part of a routed architecture, not a universal replacement. |
| OCI setup slows teams down | Use the local workbench to abstract provisioning, deployment, endpoints, and benchmarks. |
| Model quality is inconsistent | Provide recommended model presets and encourage routing when quality is insufficient. |
| Benchmarks become hard to compare | Use preset benchmark profiles and exported experiment summaries. |
| Costs are unclear | Track runtime, shape, generated output, and external-model route counts. |
| Security concerns around endpoints | Keep `llama-server` private and expose only a local proxy through SSH tunneling for the hackathon. |

## FAQ

### Are we saying CPU inference replaces GPU inference?

No. The message is that not every request requires the largest model or a specialized inference path. CPU inference can handle meaningful classes of work, especially when paired with routing.

### Why run a hackathon instead of only publishing a benchmark?

Benchmarks show performance. A hackathon shows applicability. The event lets customers test their own workflows, prompts, and routing assumptions while still collecting comparable metrics.

### Why should customers care?

Customers care because GenAI cost and operational complexity increase quickly when every request goes to the same large model. Routing creates a path to use smaller local models where they are sufficient and preserve stronger models for harder tasks.

### Why should this be attached to OCI compute?

The app gives participants a direct path from idea to running infrastructure on OCI compute. It removes much of the cloud setup friction while still showing that the endpoint is backed by real OCI resources.

### What is the simplest demo?

Deploy a small GGUF model on OCI CPU, start the local endpoint, run the direct chat sample, then run the router sample. Ask 20 mixed prompts and show how many were handled by CPU versus the external model.

### What routing logic should v1 use?

Start simple and transparent:

- short prompts to CPU
- extraction, classification, rewriting, and summaries to CPU
- long prompts or advanced mode to the larger model
- high max-token requests to the larger model

The point is not to build the perfect router on day one. The point is to make routing visible and measurable.

### What does a good participant result look like?

A good result says:

- "For this workflow, CPU handled X% of requests."
- "These prompt types worked well on CPU."
- "These prompt types required escalation."
- "This model and shape gave acceptable latency for this workload."
- "Here is the cost or token-saving implication if this route split holds."

### What are the likely CPU-suitable workloads?

Likely fits include:

- classification
- extraction
- rewriting
- short summaries
- internal assistant steps
- agent tool-planning steps
- structured transformations
- first-pass triage
- deterministic business workflow helpers

### What workloads should route away from CPU?

Likely escalation cases include:

- very long context
- long-form generation
- high-concurrency user-facing workloads
- tasks that need stronger reasoning
- tasks with strict quality or latency requirements beyond the CPU endpoint

### What should we avoid claiming?

Avoid claiming CPU is always cheaper, faster, or better. The defensible claim is that CPU inference can be good enough for important categories of GenAI work, and routing lets customers measure and exploit that.

## Pilot Plan

### Pilot Size

Start with 5 to 10 teams. This is enough to collect diverse use cases without overloading support.

### Duration

Run as a half-day or one-day event:

- 30 minutes: framing and setup
- 45 minutes: infrastructure and endpoint deployment
- 45 minutes: benchmark walkthrough
- 2 to 3 hours: app build time
- 45 minutes: demos and route-split discussion

### Required Materials

- repo access
- OCI tenancy or compartment access
- recommended CPU shapes and budget guardrails
- setup guide
- sample prompts
- sample apps
- judging rubric
- short presentation template for teams

### Judging Criteria

- clear use case
- working CPU endpoint
- meaningful routing logic
- measured route split
- benchmark evidence
- explanation of where CPU was enough
- clear escalation criteria

## Recommended Next Steps

1. Run an internal dry run using the current repo.
2. Capture two or three polished demos.
3. Tighten the participant setup guide.
4. Identify a pilot customer group.
5. Define event budget and shape guardrails.
6. Run the pilot.
7. Publish sanitized learnings and follow-up reference patterns.

## One-Sentence Positioning

CPU inference is not a replacement for every GenAI serving path; it is a practical inference tier that helps customers route intelligently, reduce unnecessary large-model calls, and make GenAI adoption more cost-aware.
