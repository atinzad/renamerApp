from unittest.mock import Mock

from app.domain.models import FileRef, OCRResult
from app.services.ocr_service import OCRService


def test_run_ocr_processes_files_in_order() -> None:
    job_files = [
        FileRef(file_id="f2", name="b.png", mime_type="image/png"),
        FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg"),
    ]
    storage = Mock()
    storage.get_job_files.return_value = job_files
    drive = Mock()
    drive.download_file_bytes.side_effect = [b"b", b"a"]
    ocr = Mock()
    ocr.extract_text.side_effect = [
        OCRResult(text="text-b", confidence=0.1),
        OCRResult(text="text-a", confidence=0.2),
    ]

    service = OCRService(drive=drive, ocr=ocr, storage=storage)
    service.run_ocr("job-1")

    assert drive.download_file_bytes.call_args_list == [(("f2",),), (("f1",),)]
    assert ocr.extract_text.call_args_list == [((b"b",),), ((b"a",),)]
    assert storage.save_ocr_result.call_args_list == [
        (("job-1", "f2", OCRResult(text="text-b", confidence=0.1)),),
        (("job-1", "f1", OCRResult(text="text-a", confidence=0.2)),),
    ]


def test_run_ocr_filters_to_matching_ids() -> None:
    job_files = [
        FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg"),
        FileRef(file_id="f2", name="b.png", mime_type="image/png"),
    ]
    storage = Mock()
    storage.get_job_files.return_value = job_files
    drive = Mock()
    drive.download_file_bytes.return_value = b"a"
    ocr = Mock()
    ocr.extract_text.return_value = OCRResult(text="text-a", confidence=None)

    service = OCRService(drive=drive, ocr=ocr, storage=storage)
    service.run_ocr("job-1", file_ids=["f1", "missing"])

    drive.download_file_bytes.assert_called_once_with("f1")
    storage.save_ocr_result.assert_called_once_with(
        "job-1", "f1", OCRResult(text="text-a", confidence=None)
    )


def test_run_ocr_sorts_by_name_then_id_when_index_ties() -> None:
    job_files = [
        FileRef(file_id="f2", name="b.png", mime_type="image/png", sort_index=1),
        FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg", sort_index=1),
        FileRef(file_id="f0", name="a.jpg", mime_type="image/jpeg", sort_index=1),
    ]
    storage = Mock()
    storage.get_job_files.return_value = job_files
    drive = Mock()
    drive.download_file_bytes.side_effect = [b"a0", b"a1", b"b2"]
    ocr = Mock()
    ocr.extract_text.side_effect = [
        OCRResult(text="text-a0", confidence=None),
        OCRResult(text="text-a1", confidence=None),
        OCRResult(text="text-b2", confidence=None),
    ]

    service = OCRService(drive=drive, ocr=ocr, storage=storage)
    service.run_ocr("job-1")

    assert drive.download_file_bytes.call_args_list == [
        (("f0",),),
        (("f1",),),
        (("f2",),),
    ]


def test_run_ocr_with_empty_file_ids_noops() -> None:
    job_files = [FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg")]
    storage = Mock()
    storage.get_job_files.return_value = job_files
    drive = Mock()
    ocr = Mock()

    service = OCRService(drive=drive, ocr=ocr, storage=storage)
    service.run_ocr("job-1", file_ids=[])

    drive.download_file_bytes.assert_not_called()
    ocr.extract_text.assert_not_called()
    storage.save_ocr_result.assert_not_called()
