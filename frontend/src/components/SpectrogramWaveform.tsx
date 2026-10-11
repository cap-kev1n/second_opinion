import React, { useMemo } from 'react';

interface SpectrogramWaveformProps {
  active?: boolean;
}

const SPECTROGRAM_COLORS = [
  '#4dcafa', // Spectrogram Blue
  '#de94e2', // Spectrogram Pink
  '#ffdd03', // Spectrogram Yellow
  '#9977ff', // Spectrogram Violet
  '#62f6b5', // Mint Pulse
  '#e96b34', // Ember Orange
];

export const SpectrogramWaveform: React.FC<SpectrogramWaveformProps> = ({ active = false }) => {
  // Generate deterministic bar heights resembling an audio speech spectrogram
  const bars = useMemo(() => {
    const count = 48;
    return Array.from({ length: count }, (_, i) => {
      // Natural voice speech waveform envelope: double peak with variable harmonic amplitudes
      const progress = i / (count - 1);
      const wave1 = Math.sin(progress * Math.PI * 3);
      const wave2 = Math.sin(progress * Math.PI * 7) * 0.4;
      const envelope = Math.sin(progress * Math.PI); // tapering at edges
      const baseHeight = Math.max(0.12, Math.abs(wave1 + wave2) * envelope);
      const normalizedHeight = Math.min(1.0, baseHeight * 0.95 + 0.08);

      const color = SPECTROGRAM_COLORS[i % SPECTROGRAM_COLORS.length];
      const animationDelay = (i * 0.04).toFixed(2);
      const animationDuration = (0.8 + (i % 5) * 0.2).toFixed(2);

      return {
        id: i,
        heightPercent: Math.round(normalizedHeight * 100),
        color,
        animationDelay,
        animationDuration,
      };
    });
  }, []);

  return (
    <div className="spectrogram-container" aria-hidden="true">
      <div className={`spectrogram-grid ${active ? 'is-active' : ''}`}>
        {bars.map((bar) => (
          <div
            key={bar.id}
            className="spectrogram-bar"
            style={{
              height: `${bar.heightPercent}%`,
              backgroundColor: bar.color,
              animationDelay: `${bar.animationDelay}s`,
              animationDuration: `${bar.animationDuration}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
};
