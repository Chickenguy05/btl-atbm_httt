const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers: options.headers
  });

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    throw new Error(data?.detail || "Yêu cầu không thành công");
  }
  return data;
}

export const api = {
  login(payload) {
    return request("/api/auth/login", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload)
    });
  },
  logout() {
    return request("/api/auth/logout", { method: "POST" });
  },
  me() {
    return request("/api/auth/me");
  },
  chain() {
    return request("/api/chain");
  },
  issueCertificate(payload) {
    return request("/api/certificates", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload)
    });
  },
  uploadCertificate(file, payload) {
    const form = new FormData();
    form.append("certificate_file", file);
    form.append("student_name", payload.student_name);
    form.append("student_id", payload.student_id);
    form.append("course_name", payload.course_name);
    form.append("issued_at", payload.issued_at);
    return request("/api/certificates/upload", {
      method: "POST",
      body: form
    });
  },
  verifyCertificate(certificateId) {
    return request(`/api/certificates/${encodeURIComponent(certificateId)}`);
  },
  verifyFile(file) {
    const form = new FormData();
    form.append("document", file);
    return request("/api/verify-file", {
      method: "POST",
      body: form
    });
  },
  users() {
    return request("/api/users");
  },
  createUser(payload) {
    return request("/api/users", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload)
    });
  },
  updateUser(userId, payload) {
    return request(`/api/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload)
    });
  },
  deleteUser(userId) {
    return request(`/api/users/${encodeURIComponent(userId)}`, {
      method: "DELETE"
    });
  }
};
