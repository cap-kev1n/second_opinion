import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { InputPage } from './pages/InputPage';
import { ReportPage } from './pages/ReportPage';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<InputPage />} />
        <Route path="/report/:runId" element={<ReportPage />} />
        <Route path="/report" element={<ReportPage />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
