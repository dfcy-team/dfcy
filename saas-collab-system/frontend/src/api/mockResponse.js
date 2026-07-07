export function mockResponse(data = {}, message = 'success') {
  return Promise.resolve({
    success: true,
    code: 'OK',
    message,
    data,
  })
}
