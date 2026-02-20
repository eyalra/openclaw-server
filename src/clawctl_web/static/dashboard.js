// OpenClaw Management Interface - Dashboard JavaScript

// Current editing context
let currentEditingUsername = null;
let currentEditingProvider = "openrouter";

// Cache for model lists (simple in-memory cache, no complex logic)
let modelListCache = null;

// API helper function
async function apiCall(endpoint, options = {}) {
    const credentials = sessionStorage.getItem("credentials");
    if (!credentials) {
        window.location.href = "/login";
        return;
    }

    const { username, password } = JSON.parse(credentials);
    const auth = btoa(`${username}:${password}`);

    const defaultOptions = {
        headers: {
            "Authorization": `Basic ${auth}`,
            "Content-Type": "application/json",
        },
    };

    const response = await fetch(`/api${endpoint}`, {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...(options.headers || {}),
        },
    });

    if (response.status === 401) {
        sessionStorage.removeItem("credentials");
        window.location.href = "/login";
        return;
    }

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
}

// Fetch model list from server (all business logic handled server-side)
async function fetchModelList(provider, refresh = false) {
    try {
        const params = new URLSearchParams({ provider });
        if (refresh) {
            params.append("refresh", "true");
        }
        
        const response = await apiCall(`/models/list?${params.toString()}`);
        return response.models || [];
    } catch (error) {
        console.error(`Failed to fetch ${provider} models:`, error);
        return [];
    }
}

// Format a single price value with appropriate precision
// Backend already returns prices as per-million-token values (e.g., "2.00" = $2.00 per million tokens)
// This function ONLY formats the number for display - NO CONVERSION
function formatPriceValue(value) {
    if (!value || value === "0" || value === 0 || parseFloat(value) === 0) {
        return "Free";
    }
    
    // Handle string values
    const num = typeof value === 'string' ? parseFloat(value) : value;
    
    if (isNaN(num) || num <= 0) {
        return "Free";
    }
    
    // OpenRouter prices are typically in the range 0.000001 to 100+
    // Format based on magnitude for readability
    
    // >= 1: show 2 decimal places (e.g., $2.00)
    if (num >= 1) {
        return num.toFixed(2);
    }
    // >= 0.1: show 2 decimal places (e.g., $0.10, $0.25, $0.40)
    if (num >= 0.1) {
        return num.toFixed(2);
    }
    // >= 0.01: show 2 decimal places (e.g., $0.03, $0.14)
    if (num >= 0.01) {
        return num.toFixed(2);
    }
    // >= 0.001: show 4 decimal places (e.g., $0.0015)
    if (num >= 0.001) {
        return num.toFixed(4);
    }
    // >= 0.0001: show 5 decimal places
    if (num >= 0.0001) {
        return num.toFixed(5);
    }
    // >= 0.00001: show 6 decimal places
    if (num >= 0.00001) {
        return num.toFixed(6);
    }
    // Very small values: show up to 8 decimal places, removing trailing zeros
    if (num > 0) {
        const formatted = num.toFixed(8);
        // Remove trailing zeros and decimal point if not needed
        return formatted.replace(/\.?0+$/, '');
    }
    
    return "Free";
}

// Format pricing for display
function formatPricing(pricing) {
    if (!pricing) return "Pricing not available";
    
    const parts = [];
    if (pricing.prompt) {
        const promptPrice = formatPriceValue(pricing.prompt);
        if (promptPrice !== "Free") {
            parts.push(`Prompt: $${promptPrice}/1M tokens`);
        } else {
            parts.push(`Prompt: Free`);
        }
    }
    if (pricing.completion) {
        const completionPrice = formatPriceValue(pricing.completion);
        if (completionPrice !== "Free") {
            parts.push(`Completion: $${completionPrice}/1M tokens`);
        } else {
            parts.push(`Completion: Free`);
        }
    }
    if (pricing.request) {
        const requestPrice = formatPriceValue(pricing.request);
        if (requestPrice !== "Free") {
            parts.push(`Request: $${requestPrice}/request`);
        } else {
            parts.push(`Request: Free`);
        }
    }
    
    return parts.length > 0 ? parts.join(", ") : "Free";
}

// Format pricing for short display (badge)
function formatPricingShort(pricing) {
    if (!pricing) return "";
    
    const parts = [];
    if (pricing.prompt) {
        const promptPrice = formatPriceValue(pricing.prompt);
        if (promptPrice !== "Free") {
            parts.push(`$${promptPrice}/1M prompt`);
        }
    }
    if (pricing.completion) {
        const completionPrice = formatPriceValue(pricing.completion);
        if (completionPrice !== "Free") {
            parts.push(`$${completionPrice}/1M comp`);
        }
    }
    if (pricing.request) {
        const requestPrice = formatPriceValue(pricing.request);
        if (requestPrice !== "Free") {
            parts.push(`$${requestPrice}/req`);
        }
    }
    
    if (parts.length === 0) {
        return "(Free)";
    }
    
    return parts.length > 0 ? `[${parts.join(", ")}]` : "";
}

// Update model options dropdown based on provider (server handles all business logic)
async function updateModelOptions(provider, refresh = false) {
    const modelSelect = document.getElementById("model-select");
    const pricingDiv = document.getElementById("model-pricing");
    
    modelSelect.innerHTML = '<option value="">Loading...</option>';
    pricingDiv.innerHTML = "";
    
    // Fetch complete model list from server (all merging/filtering done server-side)
    const models = await fetchModelList(provider, refresh);
    
    // Populate dropdown (simple display logic only)
    modelSelect.innerHTML = "";
    
    if (models.length === 0) {
        modelSelect.innerHTML = '<option value="">No models available</option>';
        return;
    }
    
    // Add search/filter input
    const existingFilter = document.getElementById("model-filter");
    if (existingFilter) {
        existingFilter.remove();
    }
    
    const filterInput = document.createElement("input");
    filterInput.type = "text";
    filterInput.id = "model-filter";
    filterInput.className = "form-input";
    filterInput.placeholder = "Filter models...";
    filterInput.style.marginTop = "5px";
    filterInput.addEventListener("input", (e) => {
        const filter = e.target.value.toLowerCase();
        Array.from(modelSelect.options).forEach(opt => {
            opt.style.display = opt.value === "__custom__" || 
                               opt.textContent.toLowerCase().includes(filter) ? "" : "none";
        });
    });
    modelSelect.parentElement.insertBefore(filterInput, modelSelect.nextSibling);
    
    // Populate dropdown with models
    models.forEach(model => {
        const option = document.createElement("option");
        option.value = model.id;
        
        // Format display text with price (server already provides formatted data)
        let displayText = model.name || model.id;
        if (model.pricing) {
            const priceParts = [];
            if (model.pricing.prompt) {
                const promptPrice = formatPriceValue(model.pricing.prompt);
                if (promptPrice !== "Free") {
                    priceParts.push(`Prompt: $${promptPrice}/1M`);
                } else {
                    priceParts.push(`Prompt: Free`);
                }
            }
            if (model.pricing.completion) {
                const completionPrice = formatPriceValue(model.pricing.completion);
                if (completionPrice !== "Free") {
                    priceParts.push(`Comp: $${completionPrice}/1M`);
                } else {
                    priceParts.push(`Comp: Free`);
                }
            }
            if (model.pricing.request) {
                const requestPrice = formatPriceValue(model.pricing.request);
                if (requestPrice !== "Free") {
                    priceParts.push(`Req: $${requestPrice}`);
                } else {
                    priceParts.push(`Req: Free`);
                }
            }
            if (priceParts.length > 0) {
                displayText += ` (${priceParts.join(", ")})`;
            } else {
                displayText += " (Free)";
            }
        }
        
        option.textContent = displayText;
        option.dataset.pricing = JSON.stringify(model.pricing || null);
        modelSelect.appendChild(option);
    });
    
    // Add custom option
    const customOption = document.createElement("option");
    customOption.value = "__custom__";
    customOption.textContent = "Custom...";
    modelSelect.appendChild(customOption);
}

// Show model selection modal
function showModelModal(username, currentModel = null) {
    currentEditingUsername = username;
    
    // Determine provider from current model
    if (currentModel) {
        if (currentModel.startsWith("anthropic/")) {
            currentEditingProvider = "anthropic";
        } else {
            currentEditingProvider = "openrouter";
        }
    }
    
    document.getElementById("provider-select").value = currentEditingProvider;
    updateModelOptions(currentEditingProvider);
    
    // Set current model if provided
    if (currentModel) {
        setTimeout(() => {
            const modelSelect = document.getElementById("model-select");
            const option = Array.from(modelSelect.options).find(opt => opt.value === currentModel);
            if (option) {
                modelSelect.value = currentModel;
                updatePricingDisplay(option.dataset.pricing);
            } else {
                // Model not in list, add as custom
                const customOption = document.createElement("option");
                customOption.value = currentModel;
                customOption.textContent = `${currentModel} (current)`;
                modelSelect.insertBefore(customOption, modelSelect.lastChild);
                modelSelect.value = currentModel;
            }
        }, 100);
    }
    
    document.getElementById("model-modal").style.display = "block";
}

// Update pricing display
function updatePricingDisplay(pricingJson) {
    const pricingDiv = document.getElementById("model-pricing");
    if (!pricingJson || pricingJson === "null") {
        pricingDiv.innerHTML = "";
        return;
    }
    
    try {
        const pricing = JSON.parse(pricingJson);
        pricingDiv.innerHTML = `<small class="pricing-info">${formatPricing(pricing)}</small>`;
    } catch (e) {
        pricingDiv.innerHTML = "";
    }
}

// Load instances
async function loadInstances() {
    try {
        const data = await apiCall("/instances/");
        const container = document.getElementById("instances-container");
        
        if (!data.instances || data.instances.length === 0) {
            container.innerHTML = "<p>No instances found.</p>";
            return;
        }
        
        container.innerHTML = data.instances.map(instance => `
            <div class="instance-card">
                <div class="instance-header">
                    <h3>${instance.username} ${instance.in_config === false ? '<span class="badge badge-warning">Not in Config</span>' : ''}</h3>
                    <div class="instance-status-badge status-${instance.status}">${instance.status}</div>
                </div>
                <div class="instance-info">
                    <div class="instance-info-item">
                        <strong>Port:</strong> ${instance.port || "N/A"}
                    </div>
                    <div class="instance-info-item">
                        <strong>Model:</strong> ${instance.model || "N/A"}
                        ${instance.model_pricing ? `<span class="model-price-badge">${formatPricingShort(instance.model_pricing)}</span>` : ''}
                    </div>
                    ${instance.management_urls && instance.management_urls.length > 0 ? `
                    <div class="instance-info-item">
                        <strong>Management URLs:</strong>
                        <ul>
                            ${instance.management_urls.map(url => `<li><a href="${url}" target="_blank" class="url-link">${url}</a></li>`).join("")}
                        </ul>
                    </div>
                    ` : ""}
                </div>
                <div class="instance-actions">
                    ${instance.status === "running" ? `
                        <button class="btn btn-secondary" onclick="stopInstance('${instance.username}')">Stop</button>
                        <button class="btn btn-secondary" onclick="restartInstance('${instance.username}')">Restart</button>
                    ` : `
                        <button class="btn btn-primary" onclick="startInstance('${instance.username}')">Start</button>
                    `}
                    <button class="btn btn-primary" onclick="showModelModal('${instance.username}', '${instance.model || ""}')">Change Model</button>
                    <button class="btn btn-secondary" onclick="viewStats('${instance.username}')">Stats</button>
                    <button class="btn btn-secondary" onclick="viewLogs('${instance.username}')">Logs</button>
                </div>
            </div>
        `).join("");
    } catch (error) {
        console.error("Failed to load instances:", error);
        document.getElementById("instances-container").innerHTML = `<p class="error">Error loading instances: ${error.message}</p>`;
    }
}

// Load users
async function loadUsers() {
    try {
        const data = await apiCall("/users/");
        const container = document.getElementById("users-container");
        
        if (!data.users || data.users.length === 0) {
            container.innerHTML = "<p>No users found.</p>";
            return;
        }
        
        container.innerHTML = data.users.map(user => `
            <div class="user-card">
                <h3>${user.name}</h3>
                <div class="user-info">
                    <div class="user-info-item">
                        <strong>Model:</strong> ${user.model || "N/A"}
                    </div>
                </div>
                <div class="user-actions">
                    <button class="btn btn-primary" onclick="showModelModal('${user.name}', '${user.model || ""}')">Change Model</button>
                </div>
            </div>
        `).join("");
    } catch (error) {
        console.error("Failed to load users:", error);
        document.getElementById("users-container").innerHTML = `<p class="error">Error loading users: ${error.message}</p>`;
    }
}

// View logs
function viewLogs(username) {
    document.getElementById("logs-username").textContent = username;
    const modal = document.getElementById("logs-modal");
    const container = document.getElementById("logs-container");
    modal.style.display = "block";
    container.innerHTML = "<p>Loading logs...</p>";
    
    // Fetch recent logs
    apiCall(`/logs/${username}?tail=100`)
        .then(data => {
            if (data.logs && data.logs.length > 0) {
                container.innerHTML = `<pre class="logs-content">${data.logs.map(log => 
                    typeof log === 'string' ? log : JSON.stringify(log)
                ).join('\n')}</pre>`;
            } else {
                container.innerHTML = "<p>No logs available.</p>";
            }
        })
        .catch(error => {
            container.innerHTML = `<p class="error">Error loading logs: ${error.message}</p>`;
        });
}

// View stats
async function viewStats(username) {
    try {
        const data = await apiCall(`/stats/${username}`);
        const statsHtml = `
            <div class="stats-card">
                <h3>Resource Usage: ${username}</h3>
                <div class="stats-grid">
                    <div class="stat-item">
                        <strong>CPU Usage:</strong> ${(data.cpu_percent || 0).toFixed(2)}%
                    </div>
                    <div class="stat-item">
                        <strong>Memory:</strong> ${formatBytes(data.memory_usage || 0)} / ${formatBytes(data.memory_limit || 0)}
                    </div>
                    <div class="stat-item">
                        <strong>Memory %:</strong> ${(data.memory_percent || 0).toFixed(2)}%
                    </div>
                    <div class="stat-item">
                        <strong>Network RX:</strong> ${formatBytes(data.network_rx || 0)}
                    </div>
                    <div class="stat-item">
                        <strong>Network TX:</strong> ${formatBytes(data.network_tx || 0)}
                    </div>
                </div>
            </div>
        `;
        alert(statsHtml.replace(/<[^>]*>/g, '')); // Simple alert for now
    } catch (error) {
        alert(`Error loading stats: ${error.message}`);
    }
}

// Format bytes
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Start instance
async function startInstance(username) {
    try {
        await apiCall(`/instances/${username}/start`, { method: "POST" });
        alert(`Started ${username}`);
        loadInstances();
    } catch (error) {
        alert(`Failed to start: ${error.message}`);
    }
}

// Stop instance
async function stopInstance(username) {
    if (!confirm(`Stop ${username}?`)) return;
    try {
        await apiCall(`/instances/${username}/stop`, { method: "POST" });
        alert(`Stopped ${username}`);
        loadInstances();
    } catch (error) {
        alert(`Failed to stop: ${error.message}`);
    }
}

// Restart instance
async function restartInstance(username) {
    if (!confirm(`Restart ${username}?`)) return;
    try {
        await apiCall(`/instances/${username}/restart`, { method: "POST" });
        alert(`Restarted ${username}`);
        loadInstances();
    } catch (error) {
        alert(`Failed to restart: ${error.message}`);
    }
}

// Load system config
async function loadSystemConfig() {
    try {
        const data = await apiCall("/system/config");
        const container = document.getElementById("system-container");
        
        const priceLimits = data.web.model_price_limits || {};
        const maxPrompt = priceLimits.max_prompt_price_per_million !== null && priceLimits.max_prompt_price_per_million !== undefined 
            ? priceLimits.max_prompt_price_per_million 
            : '';
        const maxCompletion = priceLimits.max_completion_price_per_million !== null && priceLimits.max_completion_price_per_million !== undefined 
            ? priceLimits.max_completion_price_per_million 
            : '';
        const maxRequest = priceLimits.max_request_price !== null && priceLimits.max_request_price !== undefined 
            ? priceLimits.max_request_price 
            : '';
        
        container.innerHTML = `
            <div class="config-card">
                <h3>Clawctl Configuration</h3>
                <div class="config-item"><strong>Data Root:</strong> ${data.clawctl.data_root}</div>
                <div class="config-item"><strong>Build Root:</strong> ${data.clawctl.build_root}</div>
                <div class="config-item"><strong>OpenClaw Version:</strong> ${data.clawctl.openclaw_version}</div>
                <div class="config-item"><strong>Image Name:</strong> ${data.clawctl.image_name}</div>
                <div class="config-item"><strong>Log Level:</strong> ${data.clawctl.log_level}</div>
                ${data.clawctl.knowledge_dir ? `<div class="config-item"><strong>Knowledge Dir:</strong> ${data.clawctl.knowledge_dir}</div>` : ''}
            </div>
            <div class="config-card">
                <h3>Web Interface</h3>
                <div class="config-item"><strong>Enabled:</strong> ${data.web.enabled}</div>
                <div class="config-item"><strong>Host:</strong> ${data.web.host}</div>
                <div class="config-item"><strong>Port:</strong> ${data.web.port}</div>
            </div>
            <div class="config-card">
                <h3>Model Price Limits</h3>
                <p class="config-help">Models exceeding these limits will be filtered out from the selection dropdown.</p>
                <div class="form-group">
                    <label for="max-prompt-price">Max Prompt Price (per 1M tokens, USD):</label>
                    <input type="number" id="max-prompt-price" class="form-input" step="0.000001" min="0" value="${maxPrompt}" placeholder="No limit">
                </div>
                <div class="form-group">
                    <label for="max-completion-price">Max Completion Price (per 1M tokens, USD):</label>
                    <input type="number" id="max-completion-price" class="form-input" step="0.000001" min="0" value="${maxCompletion}" placeholder="No limit">
                </div>
                <div class="form-group">
                    <label for="max-request-price">Max Request Price (per request, USD):</label>
                    <input type="number" id="max-request-price" class="form-input" step="0.0001" min="0" value="${maxRequest}" placeholder="No limit">
                </div>
                <div class="form-group">
                    <button class="btn btn-primary" onclick="savePriceLimits()">Save Price Limits</button>
                    <button class="btn btn-secondary" onclick="clearPriceLimits()">Clear Limits</button>
                </div>
            </div>
            <div class="config-card">
                <h3>System Info</h3>
                <div class="config-item"><strong>User Count:</strong> ${data.user_count}</div>
            </div>
            <div class="config-actions">
                <button class="btn btn-primary" onclick="triggerUpdate()">Rebuild & Deploy</button>
            </div>
        `;
    } catch (error) {
        document.getElementById("system-container").innerHTML = `<p class="error">Error loading config: ${error.message}</p>`;
    }
}

// Save price limits
async function savePriceLimits() {
    const maxPrompt = document.getElementById("max-prompt-price").value;
    const maxCompletion = document.getElementById("max-completion-price").value;
    const maxRequest = document.getElementById("max-request-price").value;
    
    const limits = {
        max_prompt_price_per_million: maxPrompt ? parseFloat(maxPrompt) : null,
        max_completion_price_per_million: maxCompletion ? parseFloat(maxCompletion) : null,
        max_request_price: maxRequest ? parseFloat(maxRequest) : null,
    };
    
    try {
        const result = await apiCall("/system/price-limits", {
            method: "PUT",
            body: JSON.stringify(limits),
        });
        
        alert(`Price limits saved successfully!\n\nPrompt: ${limits.max_prompt_price_per_million || 'No limit'}\nCompletion: ${limits.max_completion_price_per_million || 'No limit'}\nRequest: ${limits.max_request_price || 'No limit'}`);
        
        // Refresh models to apply filters
        await fetchOpenRouterModels(true);
        loadSystemConfig(); // Reload config to show updated values
    } catch (error) {
        alert(`Failed to save price limits: ${error.message}`);
    }
}

// Clear price limits
function clearPriceLimits() {
    document.getElementById("max-prompt-price").value = '';
    document.getElementById("max-completion-price").value = '';
    document.getElementById("max-request-price").value = '';
}

// Trigger update
async function triggerUpdate() {
    if (!confirm("Rebuild Docker image and redeploy all containers?")) return;
    try {
        const btn = event.target;
        btn.disabled = true;
        btn.textContent = "Updating...";
        const data = await apiCall("/system/update", { method: "POST" });
        alert(`Update complete: ${data.message}`);
        btn.disabled = false;
        btn.textContent = "Rebuild & Deploy";
    } catch (error) {
        alert(`Update failed: ${error.message}`);
        event.target.disabled = false;
        event.target.textContent = "Rebuild & Deploy";
    }
}

// Logout
function logout() {
    sessionStorage.removeItem("credentials");
    window.location.href = "/login";
}

// Initialize
document.addEventListener("DOMContentLoaded", () => {
    // Check for credentials
    const credentials = sessionStorage.getItem("credentials");
    if (!credentials) {
        window.location.href = "/login";
        return;
    }
    
    // Load data
    loadInstances();
    loadUsers();
    
    // Navigation
    document.querySelectorAll(".nav-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const page = e.target.dataset.page;
            document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
            e.target.classList.add("active");
            document.getElementById(`${page}-page`).classList.add("active");
            
            if (page === "system") {
                loadSystemConfig();
            }
        });
    });
    
    // Modal handlers
    const modal = document.getElementById("model-modal");
    const closeBtn = document.querySelector(".close");
    const cancelBtn = document.getElementById("cancel-model-btn");
    
    closeBtn.onclick = () => {
        modal.style.display = "none";
    };
    
    cancelBtn.onclick = () => {
        modal.style.display = "none";
    };
    
    window.onclick = (event) => {
        if (event.target === modal) {
            modal.style.display = "none";
        }
    };
    
    // Provider change handler
    document.getElementById("provider-select").addEventListener("change", (e) => {
        currentEditingProvider = e.target.value;
        updateModelOptions(currentEditingProvider);
    });
    
    // Model change handler
    document.getElementById("model-select").addEventListener("change", (e) => {
        const option = e.target.options[e.target.selectedIndex];
        updatePricingDisplay(option.dataset.pricing);
    });
    
    // Save model handler
    document.getElementById("save-model-btn").addEventListener("click", async () => {
        const modelSelect = document.getElementById("model-select");
        const modelId = modelSelect.value;
        
        if (!modelId || modelId === "__custom__") {
            alert("Please select a model or enter a custom model ID");
            return;
        }
        
        if (!currentEditingUsername) {
            alert("No user selected");
            return;
        }
        
        try {
            // Send provider info so backend knows whether to add openrouter/ prefix
            const result = await apiCall(`/users/${currentEditingUsername}/model`, {
                method: "PATCH",
                body: JSON.stringify({ 
                    model: modelId,
                    provider: currentEditingProvider || "openrouter",
                }),
            });
            
            alert(`Model updated to ${modelId} for ${currentEditingUsername}\n\nContainer is restarting to apply changes...\n\nNote: If you see "Unknown model" errors, OpenClaw may need to be updated to support this model.`);
            modal.style.display = "none";
            
            // Refresh data after a short delay to allow container restart
            setTimeout(() => {
                loadInstances();
                loadUsers();
            }, 2000);
        } catch (error) {
            let errorMsg = error.message;
            // Provide more helpful error messages
            if (errorMsg.includes("not found in OpenRouter")) {
                errorMsg += "\n\nPlease check the model name or refresh the model list from the System page.";
            }
            alert(`Failed to update model: ${errorMsg}`);
        }
    });
    
    // Refresh models button
    document.getElementById("refresh-models-btn").addEventListener("click", async () => {
        const btn = document.getElementById("refresh-models-btn");
        btn.disabled = true;
        btn.textContent = "Refreshing...";
        
        try {
            // Refresh current provider's models if modal is open
            if (currentEditingProvider) {
                await updateModelOptions(currentEditingProvider, true);
            }
            alert("Models refreshed successfully");
        } catch (error) {
            alert(`Failed to refresh models: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.textContent = "Refresh Models";
        }
    });
    
    // Logout button
    document.getElementById("logout-btn").addEventListener("click", logout);
    
    // Logs modal handlers
    const logsModal = document.getElementById("logs-modal");
    const closeLogsBtn = document.getElementById("close-logs-btn");
    closeLogsBtn.onclick = () => {
        logsModal.style.display = "none";
    };
    
    // Close logs modal when clicking X
    const logsCloseBtn = logsModal.querySelector(".close");
    if (logsCloseBtn) {
        logsCloseBtn.onclick = () => {
            logsModal.style.display = "none";
        };
    }
});

// Make functions available globally
window.showModelModal = showModelModal;
window.viewLogs = viewLogs;
window.viewStats = viewStats;
window.startInstance = startInstance;
window.stopInstance = stopInstance;
window.restartInstance = restartInstance;
window.logout = logout;
