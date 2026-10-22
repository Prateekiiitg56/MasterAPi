// npm install openai
// MASTERAPI_TOKEN=<token> node examples/node.mjs
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "http://127.0.0.1:8787/v1", apiKey: process.env.MASTERAPI_TOKEN });

const reply = await client.chat.completions.create({
  model: "router", // alias name
  messages: [{ role: "user", content: "Hello from Node!" }],
});
console.log(reply.choices[0].message.content);

// Raw passthrough to a non-LLM API stored as "elevenlabs"
const res = await fetch("http://127.0.0.1:8787/proxy/elevenlabs/v1/voices", {
  headers: { Authorization: `Bearer ${process.env.MASTERAPI_TOKEN}` },
});
console.log(res.status, (await res.json()).voices?.length, "voices");
