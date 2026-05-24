/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      boxShadow: {
        'warm': '0 4px 20px -2px rgba(251, 146, 60, 0.15)',
        'warm-lg': '0 10px 40px -5px rgba(251, 146, 60, 0.2)',
        'glass': '0 8px 32px rgba(0,0,0,0.06)',
        'glass-lg': '0 16px 48px rgba(0,0,0,0.08)',
        'card': '0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)',
        'card-hover': '0 10px 25px -5px rgba(0,0,0,0.08), 0 4px 10px -5px rgba(0,0,0,0.04)',
        'elevated': '0 20px 60px -15px rgba(0,0,0,0.15)',
        'glow-amber': '0 4px 20px rgba(251,146,60,0.25)',
      },
    },
  },
  plugins: [],
};
