/** Small stroke icon set (24px grid, currentColor). */
const Icon = ({ children, size = 22, ...rest }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
    {children}
  </svg>
);

export const HomeIcon = (p) => <Icon {...p}><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" /></Icon>;
export const RouteIcon = (p) => <Icon {...p}><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="6" r="2.2" /><path d="M8.2 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.8" /></Icon>;
export const BatteryIcon = (p) => <Icon {...p}><rect x="3" y="7" width="16" height="10" rx="2" /><path d="M21.5 10.5v3M7 10v4M10.5 10v4" /></Icon>;
export const InsightsIcon = (p) => <Icon {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Icon>;
export const MicIcon = (p) => <Icon {...p}><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></Icon>;
export const SendIcon = (p) => <Icon {...p}><path d="M4 12 20 4l-5 16-3.5-6.5z" /><path d="M11.5 13.5 20 4" /></Icon>;
export const BoltIcon = (p) => <Icon {...p}><path d="M13 2 5 13.5h6L10 22l8-11.5h-6z" /></Icon>;
export const SnowIcon = (p) => <Icon {...p}><path d="M12 2v20M3.3 7l17.4 10M3.3 17 20.7 7M9 4l3 2 3-2M9 20l3-2 3 2" /></Icon>;
export const OfficeIcon = (p) => <Icon {...p}><rect x="5" y="3" width="14" height="18" rx="1.5" /><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10.5 21v-4h3v4" /></Icon>;
export const PinIcon = (p) => <Icon {...p}><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" /></Icon>;
export const SpeakerIcon = (p) => <Icon {...p}><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" /></Icon>;
export const MuteIcon = (p) => <Icon {...p}><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="m16 9.5 5 5M21 9.5l-5 5" /></Icon>;
export const CloseIcon = (p) => <Icon {...p}><path d="M6 6l12 12M18 6 6 18" /></Icon>;
export const PlugIcon = (p) => <Icon {...p}><path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4" /></Icon>;
export const ThermoIcon = (p) => <Icon {...p}><path d="M10 13.5V5a2 2 0 0 1 4 0v8.5a4 4 0 1 1-4 0z" /></Icon>;
export const SlidersIcon = (p) => <Icon {...p}><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></Icon>;
