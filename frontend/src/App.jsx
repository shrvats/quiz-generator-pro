import { MathJaxProvider } from 'mathjax3-react'
import QuizRenderer from './components/QuizRenderer'

export default function App() {
  return (
    <MathJaxProvider>
      <div className="container">
        <h1 style={{ color: '#1a237e', textAlign: 'center' }}>
          Exam Prep Generator
        </h1>
        <QuizRenderer />
      </div>
    </MathJaxProvider>
  )
}


