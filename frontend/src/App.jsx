import { MathJaxContext } from 'better-react-mathjax'
import QuizRenderer from './components/QuizRenderer'

export default function App() {
  return (
    <MathJaxContext>
      <div className="container">
        <h1 style={{ color: '#1a237e', textAlign: 'center' }}>
          Exam Prep Generator
        </h1>
        <QuizRenderer />
      </div>
       <div className="container">
      <h1 style={{ color: 'red', textAlign: 'center' }}>
        TEST - If you see this, React is working
      </h1>
      <QuizRenderer />
    </div>
    </MathJaxContext>
  )
}



