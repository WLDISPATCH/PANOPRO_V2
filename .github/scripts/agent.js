import axios from "axios";
import fs from "fs";

const prompt = `
You are a senior software engineer.

Issue:
${process.env.ISSUE_TITLE}

Details:
${process.env.ISSUE_BODY}

Generate the required code changes. Keep edits minimal.
`;

const response = await axios.post(
  "https://api.anthropic.com/v1/messages",
  {
    model: "claude-opus-4-6",
    max_tokens: 2000,
    messages: [{ role: "user", content: prompt }]
  },
  {
    headers: {
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01"
    }
  }
);

const output = response.data.content[0].text;

// Example: write to file
fs.writeFileSync("ai-output.txt", output);
