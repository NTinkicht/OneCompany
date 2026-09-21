"use strict";
const list = document.getElementById("items");
const message = document.getElementById("message");
async function call(path, options) {
  const response = await fetch(path, {
    ...options, headers: {"Content-Type": "application/json"}
  });
  if (!response.ok) {
    const detail = await response.json();
    throw new Error(detail.error || "Request failed");
  }
  return response.status === 204 ? null : response.json();
}
async function refresh() {
  const {items} = await call("/api/items");
  list.replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = item.title + (item.done ? " (done)" : "");
    const toggle = document.createElement("button");
    toggle.textContent = item.done ? "Undo" : "Done";
    toggle.addEventListener("click", () => mutate(
      "/api/items/" + item.id, {method: "PATCH", body: JSON.stringify({done: !item.done})}
    ));
    const remove = document.createElement("button");
    remove.textContent = "Delete";
    remove.addEventListener("click", () => mutate("/api/items/" + item.id, {method: "DELETE"}));
    li.append(label, toggle, remove);
    list.appendChild(li);
  }
}
async function mutate(path, options) {
  try {
    await call(path, options);
    message.textContent = "";
    await refresh();
  } catch (error) {
    message.textContent = error.message;
  }
}
document.getElementById("create").addEventListener("submit", async event => {
  event.preventDefault();
  const input = document.getElementById("title");
  const title = input.value.trim();
  if (!title) return;
  try {
    await call("/api/items", {method: "POST", body: JSON.stringify({title})});
    input.value = "";
    message.textContent = "";
    await refresh();
  } catch (error) {
    message.textContent = error.message;
  }
});
refresh().catch(error => {message.textContent = error.message;});
