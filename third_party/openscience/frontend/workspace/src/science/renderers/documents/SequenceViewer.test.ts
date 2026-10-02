import { expect, test } from "bun:test"
import { sequenceRecords } from "./SequenceViewer"

test("preserves every FASTA record and its independent length for record selection", () => {
  const fasta = ">one\nACGT\n>two\nAA\n>three\nACG\n"
  expect(sequenceRecords(fasta)).toEqual([{ id: "one", seq: "ACGT" }, { id: "two", seq: "AA" }, { id: "three", seq: "ACG" }])
  expect(sequenceRecords({ fasta, type: "dna" }).map((record) => record.type)).toEqual(["dna", "dna", "dna"])
})

test("accepts the workspace's structured multi-record data without concatenating sequences", () => {
  expect(sequenceRecords({ sequence: "ACGT", sequences: [{ id: "one", seq: "ACGT" }, { id: "two", seq: "AA" }] })).toEqual([{ id: "one", seq: "ACGT", type: undefined }, { id: "two", seq: "AA", type: undefined }])
})
