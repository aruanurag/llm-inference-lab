import "./styles.css";

export const metadata = {
  title: "Router Chat",
  description: "Hackathon sample app routing between CPU inference and OpenAI.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
