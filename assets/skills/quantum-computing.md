---
name: Quantum Computing
description: Principles, key concepts, algorithms, hardware, and practical limitations of quantum computing.
---

# Quantum Computing

## Core principles
- **Qubit:** quantum bit that can be in a superposition `α|0⟩ + β|1⟩` (|α|²+|β|²=1), unlike a classical 0/1.
- **Superposition:** enables representing many states at once; measurement collapses to a basis state with given probabilities.
- **Entanglement:** correlated qubits whose joint state cannot be described independently; essential for many quantum algorithms and communication protocols.
- **Interference:** amplitudes combine constructively/destructively; algorithms amplify correct outcomes and cancel wrong ones.
- **Measurement & collapse:** observing yields classical outcomes and disturbs state; repeated runs (shots) estimate probabilities.
- **No-cloning:** arbitrary unknown quantum states cannot be copied perfectly.

## How computation works (high level)
1. **Initialize** qubits (often to |0…0⟩).
2. **Apply quantum gates** (unitary operations) to create/manipulate superposition and entanglement (e.g. Hadamard, Pauli-X/Y/Z, phase, CNOT, Toffoli; parameterized rotations).
3. **Measure** in a basis to obtain classical bitstrings; repeat circuit many times to build statistics.
- **Circuit model:** sequences of gates on qubits (most common). Other models: adiabatic/annealing, measurement-based.

## Important algorithms and use cases
- **Shor’s algorithm:** integer factoring/discrete log in polynomial time (threatens RSA/ECC at sufficient scale) — requires large, fault-tolerant machines.
- **Grover’s algorithm:** quadratic speedup for unstructured search (O(√N)); impacts symmetric-key security margins (e.g. motivates larger keys).
- **VQE / QAOA:** hybrid quantum-classical variational methods for chemistry/optimization on NISQ devices.
- **Quantum simulation:** modeling quantum systems (chemistry/materials) — a leading near/medium-term application.
- **Quantum error correction (QEC):** encodes logical qubits into many physical qubits (e.g. surface codes) to correct noise; key to fault tolerance.

## Hardware approaches (examples)
- **Superconducting qubits:** fast gates, cryogenic operation (IBM, Google).
- **Trapped ions:** long coherence, high-fidelity gates, slower (Quantinuum, IonQ).
- **Photonic, neutral atoms, spin qubits:** alternative platforms with different tradeoffs.
- Key metrics: qubit count, coherence times, gate fidelities, connectivity, error rates, and logical/qubit overhead.

## Current reality and limitations
- **NISQ era:** today’s devices are noisy with limited qubits; practical advantage is problem-specific and still emerging.
- **Noise/decoherence:** errors accumulate; deep circuits need error correction.
- **Resource overhead:** fault-tolerant useful algorithms (e.g. Shor for large keys) may require many high-quality physical qubits per logical qubit.
- **Not a general speedup:** quantum helps certain problem classes; most classical workloads won’t get dramatic gains.

## Practical implications
- **Cryptography:** plan migration to **post-quantum cryptography (PQC)** for long-term confidentiality (harvest-now-decrypt-later risk).
- **Getting started:** learn linear algebra/probability basics; experiment with frameworks like Qiskit, Cirq, or PennyLane and cloud-accessible simulators/hardware.
- **Evaluate claims carefully:** distinguish physical vs logical qubits, benchmark/task relevance, and demonstrated vs projected advantage.

Quantum computing is a type of computation that uses the principles of quantum mechanics to perform calculations. It is based on the idea of using qubits (quantum bits) to represent information, which can exist in multiple states at the same time. This allows for faster processing of certain types of data, but also introduces new challenges and limitations. Quantum computers can be used for simulations, cryptography, and optimization problems. However, they are still in the early stages of development and require careful control to maintain their quantum properties.
