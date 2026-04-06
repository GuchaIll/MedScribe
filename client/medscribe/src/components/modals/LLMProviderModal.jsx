import { useState, useEffect } from "react";
import PropTypes from "prop-types";

/**
 * LLM Provider Selection Modal
 * Shows available LLM endpoints (Groq, OpenAI, Claude, etc.)
 * User can select which one to use. Auto-selects if only one available.
 */
export default function LLMProviderModal({ onProviderSelected, onDismiss }) {
  const [providers, setProviders] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [autoSelected, setAutoSelected] = useState(false);

  useEffect(() => {
    fetchProviders();
  }, []);

  const fetchProviders = async () => {
    try {
      const response = await fetch("/api/llm/providers");
      if (!response.ok) throw new Error("Failed to fetch LLM providers");
      const data = await response.json();

      const available = data.providers.filter((p) => p.available);

      if (available.length === 0) {
        setError(
          "No LLM provider API keys configured. Please set at least one of: GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OPENROUTER_API_KEY in your .env file."
        );
        setLoading(false);
        return;
      }

      setProviders(available);

      // Auto-select if only one provider
      if (available.length === 1) {
        setSelectedProvider(available[0].name);
        setAutoSelected(true);
        // Auto-confirm after a brief delay
        setTimeout(() => {
          confirmSelection(available[0].name);
        }, 800);
      } else {
        // Use default if multiple available
        const defaultProvider = available.find(
          (p) => p.name === data.default_provider
        ) || available[0];
        setSelectedProvider(defaultProvider.name);
      }

      setLoading(false);
    } catch (err) {
      setError(`Error loading providers: ${err.message}`);
      setLoading(false);
    }
  };

  const confirmSelection = async (providerName) => {
    try {
      const response = await fetch("/api/llm/provider/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_name: providerName }),
      });

      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || "Failed to select provider");
      }
      await response.json();

      // Store selection in sessionStorage
      sessionStorage.setItem("selectedLLMProvider", providerName);

      onProviderSelected(providerName);
    } catch (err) {
      setError(`Failed to select provider: ${err.message}`);
    }
  };

  const handleConfirm = () => {
    if (selectedProvider) {
      confirmSelection(selectedProvider);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        backgroundColor: "rgba(0,0,0,0.7)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backdropFilter: "blur(4px)",
      }}
    >
      <div
        style={{
          backgroundColor: "#1a1a2e",
          borderRadius: 16,
          padding: 32,
          maxWidth: 500,
          width: "90%",
          boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
          border: "1px solid rgba(255,255,255,0.1)",
          animation: "slideUp 0.3s ease-out",
        }}
      >
        <h2
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: "#ffffff",
            marginBottom: 8,
            fontFamily: "'DM Sans', sans-serif",
          }}
        >
          Select LLM Provider
        </h2>

        <p
          style={{
            fontSize: 14,
            color: "#a0a0a0",
            marginBottom: 24,
            lineHeight: 1.5,
          }}
        >
          Choose which LLM endpoint to use for medical transcription and analysis.
          {autoSelected && !error
            ? " Found 1 provider - auto-selected."
            : ""}
        </p>

        {error && (
          <div
            style={{
              backgroundColor: "rgba(239,68,68,0.1)",
              border: "1px solid rgba(239,68,68,0.3)",
              borderRadius: 8,
              padding: 12,
              marginBottom: 20,
              color: "#ef4444",
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            {error}
          </div>
        )}

        {loading && !error && (
          <div
            style={{
              textAlign: "center",
              padding: "20px 0",
              color: "#666",
            }}
          >
            <div
              style={{
                display: "inline-block",
                width: 20,
                height: 20,
                borderRadius: "50%",
                border: "2px solid rgba(255,255,255,0.1)",
                borderTopColor: "#3b82f6",
                animation: "spin 0.6s linear infinite",
              }}
            />
          </div>
        )}

        {!loading && providers.length > 0 && !error && (
          <div style={{ marginBottom: 24 }}>
            {providers.map((provider) => (
              <button
                type="button"
                key={provider.name}
                onClick={() => setSelectedProvider(provider.name)}
                style={{
                  padding: 12,
                  width: "100%",
                  marginBottom: 8,
                  borderRadius: 8,
                  border:
                    selectedProvider === provider.name
                      ? "2px solid #3b82f6"
                      : "1px solid rgba(255,255,255,0.1)",
                  backgroundColor:
                    selectedProvider === provider.name
                      ? "rgba(59,130,246,0.1)"
                      : "rgba(255,255,255,0.02)",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  textAlign: "left",
                }}
              >
                <div style={{ display: "flex", alignItems: "center" }}>
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      border:
                        selectedProvider === provider.name
                          ? "6px solid #3b82f6"
                          : "2px solid rgba(255,255,255,0.3)",
                      marginRight: 12,
                      transition: "all 0.2s ease",
                    }}
                  />
                  <div style={{ flex: 1 }}>
                    <div
                      style={{
                        fontWeight: 600,
                        color: "#ffffff",
                        fontSize: 14,
                      }}
                    >
                      {provider.display_name}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "#666",
                        marginTop: 2,
                      }}
                    >
                      {provider.description}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 12 }}>
          {error && (
            <button
              onClick={onDismiss}
              style={{
                flex: 1,
                padding: "10px 16px",
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.1)",
                backgroundColor: "transparent",
                color: "#ffffff",
                fontWeight: 600,
                fontSize: 14,
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              Dismiss
            </button>
          )}
          {!error && providers.length > 0 && !autoSelected && (
            <>
              <button
                onClick={onDismiss}
                style={{
                  flex: 1,
                  padding: "10px 16px",
                  borderRadius: 8,
                  border: "1px solid rgba(255,255,255,0.1)",
                  backgroundColor: "transparent",
                  color: "#ffffff",
                  fontWeight: 600,
                  fontSize: 14,
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                }}
              >
                Skip
              </button>
              <button
                onClick={handleConfirm}
                disabled={!selectedProvider || loading}
                style={{
                  flex: 1,
                  padding: "10px 16px",
                  borderRadius: 8,
                  border: "none",
                  backgroundColor: "#3b82f6",
                  color: "#ffffff",
                  fontWeight: 600,
                  fontSize: 14,
                  cursor: selectedProvider && !loading ? "pointer" : "default",
                  opacity: selectedProvider && !loading ? 1 : 0.5,
                  transition: "all 0.2s ease",
                }}
              >
                Confirm
              </button>
            </>
          )}
        </div>
      </div>

      <style>{`
        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }

        @keyframes fadeUp {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>
    </div>
  );
}

LLMProviderModal.propTypes = {
  onProviderSelected: PropTypes.func.isRequired,
  onDismiss: PropTypes.func.isRequired,
};
