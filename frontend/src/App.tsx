import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout.tsx";
import LandingPage from "./components/LandingPage.tsx";
import PipelinePage from "./components/PipelinePage.tsx";
import ReportView from "./components/ReportView.tsx";
import BenchmarkView from "./components/BenchmarkView.tsx";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<LandingPage />} />
          <Route path="/pipeline/:jobId" element={<PipelinePage />} />
          <Route path="/report/:jobId" element={<ReportView />} />
          <Route path="/benchmark" element={<BenchmarkView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
