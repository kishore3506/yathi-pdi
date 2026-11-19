const input = $input.first().json;
const payload = input.body ?? input;

if (!Array.isArray(payload.attachments) || !payload.to || !payload.subject) {
  throw new Error('Invalid PDI email payload.');
}

const binary = {};
const attachmentFields = [];

for (const [index, attachment] of payload.attachments.entries()) {
  if (
    typeof attachment.fileName !== 'string' ||
    attachment.fileName.includes('/') ||
    attachment.fileName.includes('\\') ||
    typeof attachment.mimeType !== 'string' ||
    typeof attachment.base64 !== 'string' ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(attachment.base64)
  ) {
    throw new Error('Invalid PDI email attachment.');
  }

  const field = `pdi_attachment_${index}`;
  attachmentFields.push(field);
  binary[field] = {
    data: attachment.base64,
    mimeType: attachment.mimeType,
    fileName: attachment.fileName,
  };
}

return [{
  json: {
    ...payload,
    attachmentFields: attachmentFields.join(','),
  },
  binary,
}];
