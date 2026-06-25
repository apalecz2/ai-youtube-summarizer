import { useState } from "react";
import { api } from "../api";
import type { Quiz } from "../types";

/** Take-the-quiz UI: generate on demand, answer, then reveal correctness. */
export default function QuizView({ videoId, initial }: { videoId: string; initial: Quiz | null }) {
  const [quiz, setQuiz] = useState<Quiz | null>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);

  async function generate() {
    setBusy(true);
    setError("");
    setSubmitted(false);
    setAnswers({});
    try {
      setQuiz(await api.makeQuiz(videoId, 5));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!quiz) {
    return (
      <div className="card">
        <h3>Quiz</h3>
        <p className="muted">Test your understanding with a quick multiple-choice quiz.</p>
        <button className="primary" onClick={generate} disabled={busy}>
          {busy ? "Generating…" : "Generate quiz"}
        </button>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  const score = quiz.questions.reduce(
    (n, q, i) => n + (answers[i] === q.correct_index ? 1 : 0), 0,
  );

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Quiz</h3>
        <button onClick={generate} disabled={busy}>{busy ? "…" : "New quiz"}</button>
      </div>

      {quiz.questions.map((q, qi) => (
        <div key={qi} style={{ marginTop: 16 }}>
          <strong>{qi + 1}. {q.question}</strong>
          {q.options.map((opt, oi) => {
            const chosen = answers[qi] === oi;
            let cls = "quiz-option";
            if (submitted) {
              if (oi === q.correct_index) cls += " correct";
              else if (chosen) cls += " wrong";
            }
            return (
              <button
                key={oi}
                className={cls}
                style={chosen && !submitted ? { borderColor: "var(--accent-2)" } : undefined}
                disabled={submitted}
                onClick={() => setAnswers({ ...answers, [qi]: oi })}
              >
                {String.fromCharCode(65 + oi)}. {opt}
              </button>
            );
          })}
          {submitted && q.explanation && (
            <p className="muted" style={{ marginTop: 4 }}>{q.explanation}</p>
          )}
        </div>
      ))}

      <div style={{ marginTop: 18 }}>
        {!submitted ? (
          <button
            className="primary"
            disabled={Object.keys(answers).length < quiz.questions.length}
            onClick={() => setSubmitted(true)}
          >
            Submit answers
          </button>
        ) : (
          <strong>Score: {score} / {quiz.questions.length}</strong>
        )}
      </div>
    </div>
  );
}
