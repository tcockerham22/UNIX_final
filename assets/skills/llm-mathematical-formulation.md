---
name: LLM Mathematical Formulation
description: A mathematical framework for understanding Large Language Models covering tokenization, transformer architecture, self-attention, autoregressive training, and diffusion-based generation.
updated: 1794470025
sources: /home/connor/Projects/Ada/data/uploads/LLM.pdf
---

# Summary
This document provides a rigorous mathematical formulation of Large Language Models (LLMs), bridging the gap between high-level AI code implementations and formal mathematical theory. It aims to make LLMs accessible to mathematicians by defining them through information theory, probability, and optimization. The core thesis is that while LLMs rely on vast data and empirical success, their underlying structure can be precisely defined, allowing for theoretical studies regarding accuracy, efficiency, and robustness.

# Key Concepts & Mathematical Foundations
## 1. Tokenization and Sequence Representation
LLMs process text as sequences of tokens rather than raw characters. The document establishes notation for representing language as sequences of discrete tokens mapped into Euclidean space (embeddings). This transformation is the first step in converting unstructured text into a format suitable for mathematical manipulation.

## 2. Autoregressive Factorization and Next-Token Prediction
The fundamental methodology of LLMs is **autoregressive factorization**. The joint probability distribution of a sequence $x_1, x_2, ..., x_T$ is factored into a product of conditional probabilities:
$$P(x_1, ..., x_T) = \prod_{t=1}^{T} P(x_t | x_{<t})

The model learns to predict the next token $x_t$ given the history $x_{<t}$. This is achieved by parameterizing a function (typically a neural network) that maps the input sequence to a probability distribution over the vocabulary.

## 3. The Transformer Architecture
The standard architecture relies on the **attention mechanism**, specifically self-attention. Mathematically, attention is formulated as a mapping that takes sequences into sequences, allowing the model to learn correlations between different elements in the input regardless of their distance (long-range dependencies).
- **Self-Attention**: Computes a weighted sum of value vectors based on the compatibility between query and key vectors.
- **Positional Encoding**: Since transformers lack inherent sequential order, positional encodings are added to embeddings to retain information about token positions.
- **Layer Normalization**: Used for training stability within the network layers.

## 4. Training Objective and Optimization
Models are trained using large corpora of internet data. The objective function is typically a probabilistic loss (e.g., cross-entropy) designed to minimize the negative log-likelihood of the next token given the context. Training involves gradient descent-based methods, requiring the computation of derivatives of the model output with respect to its parameters.

## 5. Alternative Generation Methods
While autoregressive models are standard, the document discusses **diffusion-based generative modeling** as an emerging alternative for discrete sequence spaces. This approach generalizes continuous-time diffusion processes to discrete domains, offering a different pathway for sequence generation that may address limitations of purely autoregressive methods.

# Procedures and Applications
## Deployment Tasks
Once trained, these models are deployed to perform various tasks via the next-token prediction capability:
- **Text Generation**: Writing code, stories, or emails.
- **Summarization**: Condensing long documents into key points.
- **Reasoning**: Solving quantitative problems or logical puzzles.
- **Interaction**: Holding conversations and gathering follow-up information.

## Evaluation Framework
The document outlines a framework to evaluate LLM capabilities on sequence generation tasks, moving beyond simple benchmark scores to assess robustness and accuracy through mathematical lenses.

# Limitations and Challenges
Despite their success, LLMs face significant challenges:
- **Lack of Rigor**: They operate without strict logical or inferential constraints, leading to potential hallucinations or errors.
- **Resource Intensity**: Training and deployment consume enormous computational resources.
- **Limited Guarantees**: Empirical success does not equate to mathematical guarantees of correctness.

The document concludes that a precise mathematical formulation is necessary to address these shortcomings and to develop modified methodologies (such as state-space models replacing attention) that are more efficient or robust.
