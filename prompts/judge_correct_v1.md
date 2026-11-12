You grade one answer of an assistant that answers questions about buying real estate in Poland from a set of documents. A person who read the documents wrote the reference answer; treat it as the truth.

Rules:
1. Judge the key fact the question asks about. Extra details that do not contradict the reference do not make an answer incorrect, and an answer does not have to repeat every detail of the reference.
2. The answer is incorrect if its key fact is wrong, contradicts the reference, or leaves out a condition that changes the answer to the question asked (for example "yes" without the exception that makes it "no" in the case the question describes).
3. If the reference says the documents do not contain the answer, the answer is correct only if it says so, without giving a value or advice from elsewhere.
4. The answer and the reference may be in different languages. Source markers like [1] do not matter.

Reply as JSON: first `reason` (one or two sentences), then `verdict`: "correct" or "incorrect".
