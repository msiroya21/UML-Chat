1.	Can you make a chat platform that can accept a user prompt for a software design and generate the UML diagrams for the relevant software using this as the minimum input:
2.	 
3.	{
4.	   "prompt": """
5.	I am working on a compliance monitoring solution which will pull in the latest circulars from SEBI and parse them. Once it is parsed into a table to clauses, you will need to extract the following information:
6.	1. The new compliance requirements proposed by the regulator
7.	2. Gap analysis with my existing compliance setup
8.	3. The impact of these new compliance requirements on my organization at an IT and operational level
9.	""",
10.	   "diagram_types": ["sequential", "component", ...]
11.	}
12.	 
13.	 
14.	When implementing the platform, please consider the following cases:
15.	1. New user, sending you this request, you give an output
16.	2. Existing user, sending you request with an updated prompt, you need to give the updated output
17.	3. Existing user, is giving you feedback, this has to be passed onto the ART plugin of langchain to improve the model for future iterations.
18.	 
19.	Key technical considerations:
20.	1. How to generate/render the UML on UI?
21.	2. How to control/verify snytax issues in the output?
22.	3. How are we minimizing latency?
23.	4. How to collect and store feedback for the RL trainer?
24.	 
25.	 
26.	# UML in One Class: All Diagram Types
27.	 
28.	## Learning outcomes
29.	 
30.	* Know the 14 UML 2.x diagram types and when to use each.
31.	* Recognize core notations and common pitfalls.
32.	* Pick a minimal set for typical software specs.
33.	 
34.	## Big picture
35.	 
36.	* **Structure diagrams (7):** what the system *is*.
37.	* **Behavior diagrams (7):** what the system *does*.
38.	 
39.	  * Interaction diagrams (4) are a subset of behavior.
40.	 
41.	---
42.	 
43.	## Structure diagrams
44.	 
45.	**Class** — Domain/API design. Shows classes, attributes, operations, associations, inheritance, composition/aggregation, interfaces. Use for schemas and OO design.
46.	 
47.	**Object** — Snapshot of *instances* at runtime. Great for examples, test fixtures, and clarifying multiplicities.
48.	 
49.	**Component** — High-level building blocks and provided/required interfaces (ports/lollipops). Use for service/module boundaries.
50.	 
51.	**Composite Structure** — Internal wiring of a class/component: parts, ports, connectors. Use when internals matter.
52.	 
53.	**Deployment** — Runtime topology: nodes (devices/VMs/containers), execution environments, artifacts. Use for ops/DevOps views.
54.	 
55.	**Package** — Namespaces and dependencies. Use for layering and modularization.
56.	 
57.	**Profile** — Customizing UML (stereotypes, tagged values, constraints). Use to encode domain rules (e.g., «microservice», PII).
58.	 
59.	---
60.	 
61.	## Behavior diagrams
62.	 
63.	**Use Case** — Actors and goals; system scope. Use for stakeholder alignment and feature slicing.
64.	 
65.	**Activity** — Workflow/algorithms: actions, decisions, forks/joins, swimlanes, object flows. Use for business processes and pipelines.
66.	 
67.	**State Machine** — Lifecycles: states, events, guards, entry/exit actions. Use for protocols, UI widgets, order/payment states.
68.	 
69.	### Interaction (behavior subset)
70.	 
71.	**Sequence** — Time-ordered messages, sync/async, alt/loop fragments. Use for API calls and request lifecycles.
72.	 
73.	**Communication** — Same interaction as sequence but emphasizes links between participants; compact network view.
74.	 
75.	**Interaction Overview** — “Storyboard” that stitches other interactions with control flow.
76.	 
77.	**Timing** — State/value over time along lifelines; use for real-time, hardware, SLA/timeout analysis.
78.