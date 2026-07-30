declare module "pako" {
  export function deflateRaw(data: Uint8Array): Uint8Array;
  export class Inflate {
    constructor(options?: {
      raw?: boolean;
      chunkSize?: number;
    });
    err: number;
    msg: string;
    onData: (chunk: Uint8Array) => void;
    push(data: Uint8Array, final?: boolean): boolean;
  }
}
